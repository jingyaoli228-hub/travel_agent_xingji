# Travel Planning Agent

基于 **LangGraph** 的多 Agent 旅行规划系统：多轮对话、真实工具调用（高德地点/路线/天气，
海外使用 OpenStreetMap + Open-Meteo 降级，另含 Agent Reach 攻略搜索 / `opencli` 小红书
搜索）、四个 Agent（Requirement / Research / Planner / Reviewer）通过统一的 **DeepSeek**
LLM 接口协作（Kimi 为退回选项）、Human-in-the-loop 用户确认、Reviewer 反馈循环，以及一个
React + Vite + TailwindCSS 前端。

## 架构总览

```
START
  │
  ▼
requirement_agent ──(信息不完整)──► clarification ──┐
  │                                                  │ (循环直到完整)
  │(信息完整)                                        ▼
  ▼                                            requirement_agent
user_confirmation ──(用户要求修改)──► clarification / requirement_agent
  │
  │(用户确认)
  ▼
research_orchestrator ──► recommendation ──► user_selection
  ▲                                              │
  │                    (用户要求"更多")────────────┘
  │
  ▼ (用户已选定)
planner ──► validator ──► reviewer ──(score>=85 或达到最大循环)──► final_output
  ▲                            │
  └────────(score<85)──────────┘   (最多循环 3 次)
                                        │
                                        ▼
                              post_plan_feedback ◄─────────────────────┐
                                (等待用户对已生成行程的反馈)              │ (循环，直到用户满意)
                       ┌────────────────┴──────────────────┐           │
                (确认/收尾)                        (其他反馈)           │
                       ▼                                   ▼           │
                  close_out                       intent_interpreter   │
                       │                       ┌───────┼────────┐      │
                       └──────────────────────►│  SIDE_QUERY    │      │
                                                │  CLARIFICATION │      │
                                                │  NORMAL_FLOW/  │      │
                                                │  CONSERVATIVE  │      │
                                                └───┬───┬────┬───┘      │
                                          side_query┘   │    └execution_router
                                     clarify_post_plan◄─┘         │
                                                                  ▼
                                                          result_aggregation
                                                                  │
                                                                  └──────┘
```

`final_output` 之后不再直接 `END`——Stage-3 新增了**计划后反馈闭环**（见下一节），图会在
`post_plan_feedback` 处一直等待用户的下一句话，可能是确认收尾，也可能是"乌布多加瑜伽课和夜
生活，第三天重排，其他不变"这样的复杂反馈。

- **requirement_agent**：通过 DeepSeek 增量抽取/合并 `TravelRequirement`（无 Key 时降级为规则/
  启发式抽取），输出总结、已确认信息、缺失信息。
- **clarification**：等待用户补充缺失信息（LangGraph `interrupt_before`）。
- **user_confirmation**：等待用户确认需求是否正确（`interrupt_before`）。
- **research_orchestrator**：根据需求并行调用真实 Worker（高德地点 / 路线 / 天气 /
  Agent Reach / 小红书），产出 `ResearchResult`（保留 `source` 字段，便于追溯每条信息的来源）。
  Stage-4 起是**后台任务暂停点**——见下方"Stage-4"一节。
- **recommendation**：对景点/餐厅分类，生成候选列表。
- **user_selection**：等待用户选择/删除/要求更多候选（`interrupt_before`）；"更多" 只触发
  **增量搜索**（`run_incremental`），不会重新跑一遍全部 Worker。
- **planner**：结合需求 + 用户选中的地点 + 研究结果，生成逐日 `Itinerary`（境内真实交通时间来自
  高德路线规划；时间调度算法本身是确定性的，LLM 仅用于把每个行程项的推荐理由改写得更自然，
  且严格限定只能使用真实数据，不得编造）。
- **validator**：Rule-based 硬性校验（时间冲突、超预算、景点数量、重复景点、超过最晚返回时间）。
- **reviewer**：LLM Reviewer（未配置 LLM 时使用启发式打分）在 5 个维度打分，
  `score >= 85` 进入终点，否则带着 `revision_instruction` 回到 `planner`，最多循环 3 次。
- **final_output**：汇总 `TravelPlan`（概览/每日计划/路线/预算/酒店/交通/注意事项/所有信息来源）。

## Stage-3：多路融合意图识别 + 计划后反馈闭环

在保持 **恰好 4 个 Agent**（Requirement / Research Orchestrator / Planner / Reviewer，即
Presentation/Review 的落地形式）不变的前提下，新增了一条贯穿全流程的意图理解与执行链路，用来
解决"用户对已生成行程的个性化反馈无法被正确理解、要么被忽略要么触发整个行程重新规划"的问题。

```
用户输入 → Complexity Classifier (Fast/Deep 分诊)
         → [Fast Path] Pattern + Workflow State                （无网络调用）
         → [Deep Path]  Pattern + Embedding + LLM 三路并行融合   （ThreadPoolExecutor，各路独立超时/降级）
         → IntentResult（task_type/operation/target/entities/state_patch/…）
         → ExecutionPlanner → AgentRouter（按需调用 Requirement/Research/Planner）
         → AgentResultAggregator（合并/去重/冲突检测/保留-变更 diff）
         → 统一回复（新增活动的完整 Activity Card + 明确说明哪些天保持不变）
```

新增的都是**普通节点/服务/schema/工具类，不是第五个 Agent**：

| 模块 | 路径 | 作用 |
|---|---|---|
| 意图 Schema | `travel_agent/intent/schemas.py` | `IntentContext`/`ComplexityResult`/`IntentResult`/`TravelIntentEntities` 等 |
| 复杂度分诊 | `travel_agent/intent/complexity_classifier.py` | SIMPLE（走 Fast Path）/ COMPLEX（走 Deep Path） |
| 上下文构建 | `travel_agent/intent/context_builder.py` | 从 `AgentState` 提炼近期对话摘要、当前行程/候选/锁定约束等 |
| 规则解析 | `travel_agent/intent/pattern_parser.py` | 高精度 operation/day/time_period/quantity/preserve-scope 提取、否定检测 |
| 向量检索 | `travel_agent/intent/embedding_router.py` | 本地字符 n-gram 余弦相似度引擎（无需外部 Embedding API/向量库），读 `intent_data/*.jsonl` |
| LLM 解析 | `travel_agent/intent/llm_resolver.py` | 结构化 LLM 意图解析（`role="intent"`），失败自动降级为 None |
| Workflow 校验 | `travel_agent/intent/workflow_validator.py` | 引用的 day/activity 是否存在、是否触碰锁定约束、是否为旁路查询 |
| 权重融合 | `travel_agent/intent/fusion_resolver.py` | 按 `config/intent_fusion.yaml` 加权融合，按"实际到场信号"重新归一化权重 |
| 统一入口 | `travel_agent/intent/interpreter.py` | `MultiSignalIntentInterpreter`：Fast/Deep 路由 + 并行执行 |
| 执行计划/路由/聚合 | `travel_agent/execution/*.py` | `ExecutionPlanner`/`AgentRouter`/`AgentResultAggregator` |

关键设计取舍（详见各文件顶部注释）：

- **并行用 `ThreadPoolExecutor` 而非 `asyncio.gather`**：整个代码库是同步的（LangGraph 节点、
  LangChain `.invoke()`），线程池对阻塞式网络调用一样能做到并行 + 各路超时 + 失败隔离，且不需要
  在每个同步节点里包一层 `asyncio.run()`。
- **Embedding 路不接外部向量库**：项目当前没有配置 Embedding API/Key，做法与
  `memory/episodic_memory.py` 遇到无 chromadb 时一致——本地实现一个轻量替代（这里是字符 n-gram
  余弦相似度），接口留好，以后换成真实 Embedding API 直接替换 `embedding_router.py` 的实现即可。
- **Activity Card 直接扩展 `TravelExperience`**（`schemas/experience.py`），不新建平行的
  `ActivityCandidate` 模型——新增字段（`short_description`/`detailed_description`/
  `why_recommended`/`highlights`/`drawbacks`/`target_travelers`/…）全部带默认值，向后兼容；
  `to_activity_card_text()` 渲染完整卡片，不会只返回一个地名。
- **局部重规划**：`PlannerAgent.run_partial()` 只重建目标日期，其余 `DayPlan` 从上一版原样拷贝；
  `PlannerAgent.run()` 在复审循环里也会优先在**上一版行程**基础上只修正被 Reviewer 指出问题的
  那几天，而不是每次都从最初的候选池整体重建（修复了"三次复审等于重新生成三次"的问题）。
- **覆盖率闭环**：`ResearchOrchestratorAgent.check_coverage()`/`trigger_targeted_research()`
  在候选数量或类别覆盖不足时（例如用户想要瑜伽/夜生活但候选里几乎没有）自动触发定向补搜，
  复用已有的 `run_expansion`，不会等 Planner 生成完了才发现候选太单薄。
- **计划后反馈闭环**：`final_output` 不再直接 `END`，而是进入 `post_plan_feedback`
  （`interrupt_before`），接受任意后续反馈；旁路查询（天气/签证/交通）不会打断当前阶段，回答完
  自动恢复到 `post_plan_feedback` 继续等待。

意图样本库（`intent_data/`，用于 Embedding 路的本地检索）：

```
intent_data/
├── intent_taxonomy.yaml     # task_type/operation/target 三层体系 + feedback_type → 偏好增减映射
├── intent_examples.jsonl    # 24 个意图 × 8 条左右正例/边界例（口语化/简短/长句/否定/多轮指代）
├── feedback_examples.jsonl  # 16 种反馈类型（TOO_TRADITIONAL/PREFERS_WELLNESS/…）× 5-8 条
├── negative_examples.jsonl  # OOD 负例；纠错样本以 kind="correction" + review_status="pending"
│                             追加到同一文件，人工审核通过后才会被 embedding_router 采用
└── version.json
```

融合权重/阈值/Top-K/超时全部在 `config/intent_fusion.yaml` 里，不写死在代码里：

```yaml
intent_fusion:
  llm_weight: 0.60
  embedding_weight: 0.25
  pattern_weight: 0.15
  agreement_bonus: 0.08
  workflow_invalid_penalty: 0.50
  ambiguity_penalty: 0.20
  high_confidence_threshold: 0.82
  medium_confidence_threshold: 0.65
```

评测脚本（默认离线、不消耗 Kimi 额度）：

```bash
python scripts/eval_intent_accuracy.py          # Pattern+Embedding 准确率/Macro-F1（毫秒级）
python scripts/eval_intent_accuracy.py --with-llm --limit 30   # 加入真实 LLM 路（慢，需要 Key）
python scripts/eval_latency.py                  # Fast/Deep Path 各路延迟拆分
python scripts/eval_domestic_golden.py          # P0 十城黄金行程：候选相关性 + Reviewer ≥85
```

## Stage-4：DeepSeek 迁移 + 性能优化 + 真实小红书搜索 + Web 前端

在保持架构（LangGraph、恰好 4 个 Agent、Stage-3 意图链路）不变的前提下，这一阶段解决了三个问题：
Kimi 推理模型太慢、小红书搜索命令不可用、只有 API 没有可演示的界面。

```
POST /api/chat/stream (SSE)                   GET /api/research/status?session_id=
        │                                              │
        ▼                                              ▼
run_chat_turn ──► graph.stream(stream_mode="messages")   research_jobs.get_status()
        │              │ 逐 token 转发 (对同步阶段)              ▲
        │              ▼                                        │ 轮询
        │        遇到 research_orchestrator 暂停点                │
        └──────────────┴──► research_jobs.dispatch_if_needed() ──┘
                              │ 后台线程
                              ▼
                    graph.invoke(None, config)  (真正跑 research_orchestrator)
                              │
                    ResearchOrchestratorAgent.run_full()
                              │ ThreadPoolExecutor 并行
              ┌───────┬───────┼───────┬────────┬────────┬────────┐
       google_places  routes weather  xhs   web_guides visa   hotels
                              │ 全部完成后
                              ▼
                     graph.invoke 继续跑到下一个 interrupt_before
                              │ 完成 → GET /api/session/{id} 取回结果
```

- **DeepSeek 优先 + Fast/Deep 双档**：见上方"Agent 与 LLM"一节。
- **Requirement Agent 增量 Patch**：见上方对应小节。
- **小红书真实搜索**：`tools/xhs_search.py::XiaohongshuSearcher`，通过 `opencli` 驱动用户本机
  已登录的 Chrome，替换掉此前恒失败的 `xhs` CLI（Agent Reach）。
- **Research 并行化 + 后台任务 + 进度轮询**：见上方对应小节；`GET /api/research/status` 返回
  `{"status": "idle"|"running"|"done"|"error", "progress": {"google_places": "running"|"done", ...}}`，
  `GET /api/session/{session_id}` 在后台任务完成后取回最终状态（不注入新消息）。
- **SSE Token 流式输出**：`POST /api/chat/stream` 用 `graph.stream(..., stream_mode="messages")`
  替代 `graph.invoke(...)`——LangGraph 会自动为节点内**任何** LLM 调用（哪怕节点代码只是普通调用
  `.invoke()`）产出逐 token 事件，不需要改任何节点/Agent 代码。触发后台 Research 任务的那一轮
  没有可流式输出的内容（真正的搜索结果文本产生于请求之外的后台线程），直接返回一条 `final` 事件，
  由前端转去轮询 `/api/research/status`。
- **前端**（`frontend/`，React + Vite + TypeScript + TailwindCSS）：首页 + 聊天页
  （消息流 + 需求状态卡 + 实时搜索进度 + 候选体验列表 + 逐日行程卡片），风格参照 ChatGPT/
  Claude/Notion AI。候选选择阶段沿用现有的**对话式**交互（在聊天框里说"去掉XX"/"帮我推荐"），
  没有额外发明选择 API。

实测验收（真实 DeepSeek + Google APIs + `opencli`，见 §"Agent 与 LLM"）：简单需求收集/补充
单轮 <2s；完整并行 Research 约 30s 上下（真实网络延迟主导，见下）。

## 真实工具 vs. 仍为估算/mock 的部分

| 数据 | 来源 | 说明 |
|---|---|---|
| 景点 / 餐厅 / 酒店候选 | **高德地点搜索 2.0**；海外降级到 **OpenStreetMap Nominatim** | 高德提供国内评分/营业时间但不提供评论正文；海外公开数据通常无评分 |
| 交通时间 | **高德路线规划 2.0** `calculate_route` | 中国大陆真实路线；海外普通 Key 不支持，失败时明确标注并使用 Planner 的预估兜底 |
| 天气 | **高德天气**；海外或第 5-16 天降级到 **Open-Meteo** | 高德约 4 天且无降雨概率；缺失值保持为空，不编造 |
| 大众攻略（web） | **Agent Reach**（用户本地安装的第三方 CLI）`search_travel_guides` | 依赖用户自行安装配置；未安装时返回 `success:false` + 安装指引 |
| 小红书热门玩法 | **`opencli` + 本机已登录 Chrome**（`tools/xhs_search.py::XiaohongshuSearcher`） | Stage-4：真实数据（标题/作者/点赞数/链接），通过 `opencli xiaohongshu search` 驱动用户自己已登录的小红书网页版；未安装 `opencli` 或未登录时返回 `success:false` + 安装指引。`content`/`tags` 字段不由 search 级别的调用填充（只有 `opencli xiaohongshu note <id>` 才返回正文，逐条调用会超出研究耗时预算），如实留空 |
| 签证信息 | `tools/visa.py` | **仍为 mock**（本轮范围之外，没有对接的签证 API/Key） |
| 机票价格 | `research_agent._flight_worker` | **仍为规则估算**（没有对接的机票搜索 API/Key），字段中已标注 |
| 景点门票价格 | — | 高德地点不提供可靠门票价格，`ticket_price` 如实留空，不编造 |

## Agent 与 LLM：DeepSeek 优先 + Fast/Deep 双档

Stage-4 起，所有四个 Agent（以及 Stage-3 意图解析器）都通过
`travel_agent/config/llm.py` 里唯一的 `get_llm(role=..., tier=...)` 工厂函数获取模型客户端，
没有任何 Agent 自己 `ChatOpenAI(...)`。**DeepSeek 是默认后端**（配置了 `DEEPSEEK_API_KEY` 即启用），
按 `tier` 选择模型：

| tier | 模型 | 用于 |
|---|---|---|
| `"fast"`（默认） | `deepseek-chat` | 需求增量抽取、目的地复杂度判断、意图识别、评审打分、Research/Planner 的文案润色——**本项目里目前所有调用点** |
| `"deep"`（预留，当前无默认调用点） | `deepseek-reasoner` | 留给未来真正需要多步推理的任务 |

实测：`deepseek-reasoner` 对"把这段话改写得更自然"这类**受限输出**的任务仍会输出大段思维链
（一次 Activity Card 润色调用测得 6366 个输出 token、约 70 秒），完全不适合本项目任何一个调用点，
详见 `config/llm.py` 顶部注释。另外 `deepseek-reasoner` **不支持 `tool_choice`/函数调用**（实测
报错 `"Thinking mode does not support this tool_choice"`），所以任何用到
`with_structured_output(...)` 的调用点都固定用 `tier="fast"`；同理，`with_structured_output(...)`
必须显式传 `method="function_calling"`（DeepSeek 拒绝 langchain_openai 对 pydantic 目标的默认
`response_format=json_schema` 模式，实测报错 `"This response_format type is unavailable now"`）。

未配置 `DEEPSEEK_API_KEY` 时退回 Kimi（角色专属 Key 优先于共享的 `KIMI_API`），都未配置时退回
规则/启发式实现（各 Agent 离线可跑的兜底路径不变）。Kimi 的 `kimi-k2.x`/`k3` 是推理模型，只接受
`temperature=1`，`config/llm.py` 走 Kimi 分支时会自动强制该值，且忽略 `tier`。

每次 LLM 调用都会记录延迟与 token 用量日志（`travel_agent/utils/llm_logging.py`），格式：
```
[LLM] Requirement Agent deepseek-chat 0.8s (in=934 out=13 tokens)
```

每个 Agent 的 System Prompt 独立维护在 `prompts/*.md`，由 `travel_agent/prompts_loader.py`
在 Agent 初始化时读取。

### Requirement Agent：增量 Patch，而非整体重生成

`RequirementAgent._extract_with_llm` 不再要求 LLM 每轮都输出完整的 `TravelRequirement`
JSON——那样 prompt/schema 都大，输出慢。现在只要求纯文本 JSON `{"updates": {...}}`（本轮新增/
变更的字段），不使用 `with_structured_output`/json_schema，由 Python 侧 `_merge_patch()` 合并：
标量字段"有新值则覆盖"，列表字段（`interests`/`experience_preferences`/…）"新增去重"而非整体替换。
`pace` 等封闭枚举字段额外做同义词归一化（例如把英文的 `"relaxed"` 纠正回 `"松弛"`）——实测
DeepSeek 偶尔会用英文回答，而下游 `apply_defaults()` 是按中文字符串精确匹配的。

### Research：并行 Worker + 后台任务

`ResearchOrchestratorAgent.run_full()` 用 `ThreadPoolExecutor` 并行跑 Google Places / 大众攻略 /
小红书 / 签证 / 天气 / 路线 / 酒店这些互相独立的 Worker（而不是依次跑），单个 Places 搜索计划内部
也按标签/关键词并行搜索（各分组的重复项在合并后按名字去重）。Activity Card 的 LLM 润色文案上限
`_MAX_LLM_CARD_ENRICHMENT`（当前 12 条，按热度取前 N）——不加上限的话，一次真实的多标签搜索
（20+ 候选）单次润色调用能跑到 90 秒以上，比整个并行 Places 搜索都慢，其余候选仍有规则兜底的
完整文案，只是不经 LLM 润色。

`research_orchestrator` 节点是 Stage-4 新增的"后台任务"暂停点（`workflow.py` 的
`INTERRUPT_BEFORE`）：无论是初始搜索、"更多"反馈、还是 Planner 触发的自动扩展搜索，图执行到这里
都会暂停，由 `travel_agent/execution/research_jobs.py` 派生一个后台线程真正执行（进程内内存
存储任务状态，无需额外队列基础设施），使触发它的那次调用不必阻塞整个请求。`api/chat.py::
run_chat_turn` 默认 `wait_for_research=True`——会等后台任务跑完再返回，这保持了 CLI/`demo.py`/
测试套件原有的"同步"契约不变（只是因为并行化跑得更快了）；`POST /api/chat/stream`（见下）则用
`wait_for_research=False`，立即返回，交给前端轮询 `GET /api/research/status`。

实测（真实 DeepSeek + Google APIs + `opencli`）：简单需求收集/补充单轮 <2s；一次完整并行 Research
（东京 5 天，含小红书真实搜索）约 30s 上下，取决于 Google Places/Routes 的真实网络延迟。

## 目录结构

```
main.py                       # 交互式 CLI 入口
travel_agent/
├── main.py                   # FastAPI 入口 (含 CORS)
├── api/
│   ├── chat.py                 # POST /chat, GET /api/research/status, GET /api/session/{id}
│   └── chat_stream.py           # POST /api/chat/stream (SSE，Stage-4)
├── graph/
│   ├── workflow.py            # StateGraph 构建、条件边、interrupt_before、checkpoint
│   ├── state.py                # AgentState (TypedDict)
│   └── nodes.py                 # 各节点函数
├── agents/
│   ├── requirement_agent.py     # 需求收集 (DeepSeek 增量 Patch + 离线启发式兜底)
│   ├── research_agent.py         # Research Orchestrator + 并行 Worker + Activity Card 富化 + 覆盖率闭环
│   ├── recommendation_agent.py   # 候选分类与自动挑选
│   ├── planner_agent.py           # 逐日行程规划（确定性调度 + LLM 理由润色 + 局部重规划 run_partial）
│   └── reviewer_agent.py           # Rule Validator + LLM Reviewer
├── intent/                         # Stage-3: 多路融合意图识别（普通服务，非 Agent）
│   ├── schemas.py / config.py / data_store.py
│   ├── complexity_classifier.py / context_builder.py
│   ├── pattern_parser.py / embedding_router.py / llm_resolver.py
│   ├── workflow_validator.py / fusion_resolver.py / interpreter.py
├── execution/                      # Stage-3/4: 执行计划/路由/结果聚合/后台 Research 任务（普通服务，非 Agent）
│   ├── schemas.py / execution_planner.py / agent_router.py / result_aggregator.py
│   └── research_jobs.py            # Stage-4: 后台 Research 任务 + 进度轮询
├── tools/                       # 真实 Tool 实现
│   ├── google_places.py           # Google Places API (New): search_places / get_place_details
│   ├── google_routes.py           # Google Routes API: calculate_route
│   ├── weather.py                  # Google Maps Platform Weather API: get_weather
│   ├── search.py                    # Agent Reach: search_travel_guides (web 大众攻略)
│   ├── xhs_search.py                 # Stage-4: opencli + 本机 Chrome 小红书搜索
│   └── visa.py                       # 仍为 mock（本轮范围之外）
├── schemas/                      # Pydantic 数据模型（含 experience.py：Activity Card 数据结构）
├── prompts_loader.py               # 读取 prompts/*.md 的小工具
├── utils/logging.py, llm_logging.py  # Agent/Tool/LLM 调用日志（耗时、token、成功/失败）
├── memory/redis_memory.py           # Redis 接口 + 内存兜底
├── config/settings.py, llm.py        # 环境变量配置 + 统一 DeepSeek/Kimi LLM 工厂 (Fast/Deep tier)
├── tests/                            # pytest 用例（mock 网络/LLM 边界，离线可跑）
intent_data/                      # 意图/反馈/负例样本库 + 三层分类体系（供 Embedding 路检索）
config/intent_fusion.yaml         # 融合权重/阈值/Top-K/超时（不写死在代码里）
scripts/                           # eval_intent_accuracy.py / eval_latency.py（默认离线评测）
prompts/                          # 四个 Agent + 意图 LLM 解析器的 System Prompt
frontend/                         # Stage-4: React + Vite + TypeScript + TailwindCSS Web 前端
├── src/pages/                       # LandingPage / ChatPage
├── src/components/                   # 消息气泡/输入框/需求卡/搜索进度/候选列表/行程卡片
├── src/hooks/useChatSession.ts        # 会话状态 + SSE 流式接入 + Research 进度轮询
├── src/api/client.ts                   # postChatStream / getResearchStatus / getSession
└── vite.config.ts                       # dev-server 代理 /api,/chat -> :8000
demo.py                           # 端到端 demo 脚本（会真实联网调用；含计划后反馈场景）
requirements.txt
.env.example
```

## 运行方式

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

填入：

- `DEEPSEEK_API_KEY`（**推荐，默认 LLM 后端**）——去 https://platform.deepseek.com 申请。
  可选 `DEEPSEEK_FAST_MODEL`/`DEEPSEEK_DEEP_MODEL`（默认 `deepseek-chat`/`deepseek-reasoner`，
  见上方"Agent 与 LLM"一节的 tier 说明）。
- 未配置 `DEEPSEEK_API_KEY` 时退回 `KIMI_API`（或角色专属的 `KIMI_REQUIREMENT_API`/
  `KIMI_RESEARCH_API`/`KIMI_PLANNER_API`/`KIMI_REVIEWER_API`/`KIMI_INTENT_API`）。
- `AMAP_WEB_SERVICE_KEY`（高德控制台创建的 Web 服务 Key，用于后端地点/路线/天气）
- Web 工作台地图另需 `VITE_AMAP_JS_API_KEY`，启用安全密钥时再填 `VITE_AMAP_JS_SECURITY_CODE`。
  服务端 Key 不得放入浏览器变量。原生微信小程序的对话与行程页不依赖 JS Key。
- 小红书真实搜索：在本机安装 [opencli](https://www.npmjs.com/package/opencli)
  （`npm i -g opencli`），并在 Chrome 里登录小红书账号（`opencli xiaohongshu login`，或直接在
  Chrome 里正常登录网页版即可）——`opencli` 会驱动这个已登录的 Chrome 会话，不需要额外 API Key。
  可选 `XHS_SEARCH_CMD` 自定义命令模板。
- 如果需要真实的大众攻略（web）搜索：按 https://github.com/Panniantong/agent-reach 安装配置
  Agent Reach，并把 `AGENT_REACH_SEARCH_CMD` 改成你本机实际可用的命令模板

**不配置任何 LLM Key 也完全可运行** —— Requirement Agent 与 Reviewer 会自动降级为规则/启发式
实现；不配置 `AMAP_WEB_SERVICE_KEY`/`opencli` 时各 Tool 会返回 `{"success": false, "error": "..."}`，
Research 会如实提示数据不可用而不是编造。

### 3. 运行交互式 CLI

```bash
python main.py
```

输入你的旅行需求（例如 `帮我规划东京5天旅行，预算8000人民币，喜欢购物和拍照`），按提示多轮
对话即可。

### 4. 运行脚本化 Demo

```bash
python demo.py
```

会自动完成一次完整闭环（需求确认 → 真实 Research → 候选推荐 → 自动选择 → itinerary 生成 →
reviewer 打分/优化循环 → final output），最终 `TravelPlan` 保存到 `demo_final_plan.json`；
随后还会跑一轮 **Stage-3 计划后反馈场景**（"这些景点有点太传统了，想多安排一些瑜伽和夜生活体验，
第三天下午重新安排一下，其他天不要动"）——打印出解析到的 `IntentResult`，验证局部重规划只改动了
被要求的那一天，并返回带完整介绍的新增活动，最后用"确认"收尾。

> 配置 DeepSeek 后一次完整 Demo 实测约 1-2 分钟（主要是真实 Google Places/Routes 的网络延迟）；
> 若仍用 Kimi，单次 LLM 调用实测可能达到 60-100 秒；未配置任何 Key 时会自动降级为离线启发式
> 实现，跑得快得多。

### 5. 启动 API 服务

```bash
uvicorn travel_agent.main:app --reload --port 8000
```

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "demo-1", "message": "我想10月去东京5天，两个人，预算2万元，喜欢购物和美食，不想太累"}'
```

继续对话时用同一个 `session_id` 发送下一条消息（例如 `"确认"`），即可从暂停点恢复
（LangGraph `MemorySaver` checkpointer，进程内存持久化）。`POST /chat` 会阻塞到整轮结束
（含 Research，见"Stage-4"一节）；前端改用 `POST /api/chat/stream`（SSE）+
`GET /api/research/status` 轮询，Research 阶段不阻塞请求。

### 6. 启动前端

```bash
cd frontend
npm install
npm run dev
```

打开 http://localhost:5173——Vite dev-server 已配置 `/api`、`/chat` 反向代理到
`http://localhost:8000`（见 `vite.config.ts`），所以需要**先启动第 5 步的后端**。首页填入目的地
进入聊天页，或直接点"直接进入对话"跳过首页。

### 7. 运行测试

```bash
pytest travel_agent/tests -v
python scripts/eval_domestic_golden.py --json-output output/domestic-golden-latest.json
```

测试在 HTTP/subprocess/LLM 调用边界打桩（见 `tests/conftest.py`），不发真实请求、不消耗
DeepSeek/Kimi/Google 额度，全程离线快速运行（含 `test_api_endpoints.py`：用 FastAPI
`TestClient` 覆盖 SSE 流式端点 + Research 后台任务 + 状态查询接口）。

P0 国内黄金回归固定覆盖北京、上海、成都、西安、杭州、南京、重庆、广州、苏州和厦门；
每条同时校验明确必去、明确排除、偏好候选占比以及生产 `ReviewerAgent` 分数。脚本任一案例
低于 85 分即以非零状态退出，可直接作为 CI 门禁。

## 已知限制

- 普通高德 Web 服务 Key 的路线规划只覆盖中国大陆；东京等海外目的地的地点和天气可走免费公开
  数据降级，但海外公交/步行路线仍会回退到明确标注为预估的时长。
- 高德天气本身不返回降雨概率，字段保持为空；Open-Meteo 降级结果有概率时才展示。
- 大众攻略（web）搜索依赖用户本地安装的 Agent Reach，具体可用的上游命令因用户配置而异，需要
  用户自行核对 `.env` 里的 `AGENT_REACH_SEARCH_CMD`。
- 小红书搜索依赖本机安装的 `opencli` + 已登录的 Chrome 会话；`opencli xiaohongshu search` 的
  `content`（正文）/`tags` 字段不会被填充——只有 `opencli xiaohongshu note <id>` 才返回正文，
  逐条调用会明显拖慢单次 Research（见 `tools/xhs_search.py` 顶部注释），如实留空而非编造。
- 签证信息、机票价格仍为规则/mock 估算（本轮范围之外，没有对接的 API/Key）。
- 景点门票价格高德地点不提供，如实留空，不参与预算计算（预算里景点花费会偏低）。
- Checkpointer 当前使用 `MemorySaver`（进程内存），生产环境建议替换为 Redis/Postgres-backed
  checkpointer；`memory/redis_memory.py` 已提供 Redis 接口用于会话元数据持久化。Stage-4 的
  Research 后台任务状态（`execution/research_jobs.py`）同样是进程内内存，不跨进程/重启持久化——
  单进程部署下没有问题，多进程/多副本部署需要改造为共享存储（Redis 等）。
- Research 的耗时下限主要由 Google Places/Routes 的真实网络延迟决定（多标签搜索时并行执行，
  但单个标签内的"搜索 + 详情"仍是几次真实网络往返），实测约 30 秒上下浮动；LLM 部分
  （DeepSeek fast tier）已不是瓶颈。
- Planner 的交通时间计算目前对每个行程项都单独调用一次 Google Routes（未并行化，本轮范围
  聚焦在 Research 阶段），行程天数越多、每日景点数越多，Planner 阶段的真实网络调用也越多。
# 第七轮：约束规划与 TripCraft 确定性指标

现有四个 Agent 保持不变。主链在普通服务节点中增加
`ConstraintBuilder → ConstraintValidator → TripCraftMetricEvaluator`，Planner 最多尝试三次；
通过即 early stop，可修复问题只把受影响日期/POI 交给 `run_partial`，P0 不可满足则返回
`NEEDS_CONSTRAINT_RELAXATION`，不会静默放宽用户条件。最佳方案按 P0、P1 违规数、四项连续指标
依次做字典序选择，连续分数不能覆盖硬约束。

四项指标没有统一总分：Meal 使用用餐中点与时长的二元高斯密度除以均值点最大密度；
Attraction 使用按旅行者类型变化的泊松景点数概率乘持续时间高斯项；Spatial 在 5,000 米内线性
从 1 降到 0.5，之后按 `0.5 exp(-0.0002(d-5000))` 衰减；Persona 严格模式只嵌入
Traveler Type、Purpose of Travel、Spending Preference、Location Preference，使用本地
`bert-base-uncased`、attention-mask mean pooling 和 cosine similarity。缺模型或 POI 分类/公交距离时
记录 `metric_missing_data` 与 coverage，绝不补高分。

3/5/7 天参数和 15 类景点时长来自 TripCraft（ACL 2025 long paper 834）的公开公式/类别表。
其他天数使用最近参数桶，并在报告中明确标为“工程适配”；`mixed` 画像加权同样标为工程扩展。
各维度阈值位于 `tripcraft_parameters.py`，需用项目验证集分别校准，尤其 Attraction 不复用 0.7 阈值。

长期画像采用字段级更新：value、confidence、scope、explicitness、evidence、source_turn_ids、
last_updated_at。一次“这次想潜水”进入 trip-specific 兴趣，不覆盖长期 traveler_type；冲突证据保留，
确定性 merger 只接受白名单字段更新。三轮过程见 `docs/round7_three_attempt_example.md`。

## 第八轮：可视化规划工作台

Planner 产出首版行程后，React 页面切换为固定对话栏、独立滚动行程栏和全高高德地图的三栏工作台；
窄屏改为两行或纵向布局。日期、卡片、Advanced Marker 和路线段共享选择状态，切换日期会销毁旧覆盖物并
重新 `fitBounds`。真实 Routes polyline 按交通方式着色；请求失败时只显示带警告的虚线视觉提示，绝不把
经纬度直线描述成真实路线。

workspace API 使用 `trip_id + plan_version + request_id`。POI 插入先生成不污染正式计划的 patch 预览，
确认后以乐观锁提交；仅替换目标 `DayPlan`，其他日期及用户锁定节点保持不变。提交后重新执行确定性约束与
TripCraft 指标。酒店候选来自 Places `lodging` 搜索，使用评价量稳定化后的评分参与排序；缺少供应商房价、
库存或客房规则时分别显示“实时价格待确认”与 `unknown`，不做推测。

缓存 TTL：Place Details 7 天、酒店 12 小时、POI 搜索 3 小时、路线 15 分钟。
`VITE_AMAP_JS_API_KEY` 仅供浏览器高德 JavaScript API，并应限制域名；`AMAP_WEB_SERVICE_KEY`
仅供后端并应限制服务器 IP 与服务范围。后端 Key 从不进入前端响应或 Vite 环境。

行迹小程序 P0 与逐轮代码说明见 [`docs/xingji-p0/implementation-log.md`](docs/xingji-p0/implementation-log.md)；生产手机入口密钥、Cloudflare Tunnel 和微信 HTTPS 域名登记步骤见 [`docs/xingji-p0/deployment.md`](docs/xingji-p0/deployment.md)。
