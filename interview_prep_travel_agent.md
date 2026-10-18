# Travel Agent 项目面试问答（按预估提问概率排序）

> 基于当前代码库（LangGraph 四 Agent 架构 + Stage-3 意图融合 + Stage-4 真实工具/流式 + Round-6 RAG/分层记忆/严格评测）整理，每条答案标注了对应的核心文件，回答时可以直接引用文件名/机制名增加可信度。

---

## 1. 介绍 Travel Agent 的整体架构和完整执行链路

核心是 **LangGraph StateGraph + 恰好 4 个业务 Agent**（Requirement / Research Orchestrator / Planner / Reviewer），后续三轮迭代都刻意"不新增第五个 Agent"，新能力全部做成普通 service/node。

主链路：

```
requirement_agent（DeepSeek 增量 Patch 抽取，无 Key 时规则兜底）
  → clarification / region_confirmation（复杂目的地如巴厘岛先问是否分区域）/ user_confirmation（均 interrupt_before）
  → research_orchestrator（并行 Worker：Google Places/Routes/Weather/小红书/攻略/签证，
     Stage-4 起是"后台任务暂停点"，由 execution/research_jobs.py 起后台线程真正执行）
  → recommendation → user_selection（interrupt_before，支持"更多"触发增量搜索）
  → planner（层次化规划：Region → Experience → Timeline，确定性调度 + LLM 只润色文案）
  → validator（规则硬校验）→ reviewer（LLM 5 维打分，score<85 且循环<3 次回到 planner）
  → [Round-6] strict_evaluation（8 维 + 9 条硬扣分规则，循环<2 次回到 planner/研究）
  → final_output → post_plan_feedback（interrupt_before，计划后持续反馈闭环）
```

`post_plan_feedback` 之后不是 `END`：Stage-3 叠加了一条 **意图理解 + 执行** 链路（`intent/` + `execution/`，都是普通模块不是 Agent）：Complexity Classifier 做 Fast/Deep 分诊 → Fast Path（Pattern + Workflow State，无网络调用）或 Deep Path（Pattern + Embedding + LLM 三路并行融合）→ `IntentResult` → `ExecutionPlanner` → `AgentRouter`（按需只调用被触及的 Agent）→ `AgentResultAggregator`（合并/diff/一致性校验）→ 统一回复，再回到 `post_plan_feedback` 继续等待。

人机协作靠 LangGraph 的 `interrupt_before`（`clarification`/`user_confirmation`/`user_selection`/`research_orchestrator`/`post_plan_feedback`）配合 `MemorySaver` checkpointer 按 `session_id`（=`thread_id`）持久化状态；恢复靠 API 层 `update_state()` 注入新消息后 `invoke(None, config)`。

---

## 2. 为什么使用四个 Agent，而不是单 Agent？

- **职责边界清晰、可分别测试/降级**：四个 Agent 每个都有独立的离线启发式兜底路径（无 LLM Key 也能跑），拆开才能各自做 dual-path 设计，合成一个 Agent 就没法局部降级。
- **确定性与概率性的配比不同**：Planner 的时间调度（地点先后顺序、交通时间）必须是确定性算法（真实调 `calculate_route`），LLM 只负责把 `reason` 文案写自然；Reviewer 必须独立于生成者才能做有效校验（自己评自己没有意义）；单 Agent 会把"该确定性的"和"该生成式的"逻辑混在同一个 prompt 里，既难保证正确性也难调试。
- **规则闸门 + LLM 闸门要分层**：`validator`（rule-based）→ `reviewer`（LLM 5 维）→ `strict_evaluation`（LLM 8 维 + hard_penalty）是三层递进的质量闸门，各自成本/延迟/严格程度不同，单 Agent 没法承载这种分层。
- **可按需路由，不必每次全跑**：Stage-3 的 `AgentRouter` 可以只调用被触及的 Agent（比如只改 Requirement 的一个偏好字段，不必重跑 Planner），这依赖 Agent 边界清晰；单体 Agent 做不到"只重跑一部分"。
- **明确的设计取舍**：架构设计文档里反复强调"不新增第五个业务 Agent"——RAG 检索链路、意图理解、严格评测这些新能力全部做成 `rag/`、`intent/`、`evaluation/` 下的普通函数/服务，而不是包装成新 Agent，避免 Agent 数量和职责边界失控。

---

## 3. LangGraph 的 State、节点、边和条件分支怎么设计？

- **State**：`AgentState` 是一个 `TypedDict`，`conversation_history` 用 `Annotated[List[dict], operator.add]` 做累加型 reducer，其余字段（`travel_requirement`/`itinerary`/`review_report`/`stage`/`current_node`/`need_user_input` 等）默认 last-write-wins。
- **节点**：`requirement_agent`/`clarification`/`user_confirmation`/`research_orchestrator`/`recommendation`/`user_selection`/`planner`/`validator`/`reviewer`/`strict_evaluation`/`final_output`/`post_plan_feedback` + 意图相关节点，每个节点是一个瘦函数，业务逻辑在对应 Agent/service 里，节点只做"调用 + 拼装 state 更新"。
- **条件边**：`graph.add_conditional_edges(source, route_fn, mapping)`，路由函数读当前 state（节点更新已经 merge 进去之后的 state）返回下一个节点名字符串。典型例子：`route_after_reviewer` 读 `review_report.passed` 和 `review_loop_count` 决定去 `planner` 还是 `final_output`。
- **循环边防死循环**：每一条循环边都配一个 state 里的计数字段 + `settings` 里的硬上限——`reviewer↔planner` 最多 `max_review_loops`（默认 3）次，`planner↔research_orchestrator` 补充搜索最多 `max_research_expansion_loops`（默认 2）次，`strict_evaluation↔planner` 最多 `max_revision_rounds`（默认 2）次，超预算后强制放行（打上"已达上限"的标注）而不是无限循环。
- **人机协作**：`INTERRUPT_BEFORE = ["clarification", "region_confirmation", "user_confirmation", "user_selection", "research_orchestrator", "post_plan_feedback"]`（`graph/workflow.py`）让图在这几个节点执行前暂停，配合 `MemorySaver` checkpointer 按 `thread_id` 存快照；`region_confirmation` 是 Stage-2 加的（复杂目的地如"巴厘岛"先问要不要分区域规划）；`research_orchestrator` 比较特殊——它是 Stage-4 新增的"后台任务暂停点"，不管是首次搜索、"更多"反馈还是 Planner 触发的自动扩展，图执行到这里都会暂停，由后台线程真正跑完再 `invoke(None,...)` 推进，避免同步阻塞整个 HTTP 请求。

---

## 4. 用户修改需求后如何做局部重规划？

`PlannerAgent.run_partial()` 只重建 `target_days` 指定的那几天，其余 `DayPlan` 从上一版原样拷贝，而不是从候选池整体重新生成。`target_days` 的确定逻辑在 `execution/agent_router.py`：

- 用户明确说了"第 X 天" → `target_days=[X]`；
- 区域替换（比如"把 Canggu 换成 Ubud"）没有显式天数，但 `preserve_other_days` 默认 True → 用 `execution/region_resolution.py::resolve_target_days_for_region` 反查这个区域当前占用了哪几天。

同一个"局部优先"的原则也用在 Reviewer 循环里：复审不合格时，Planner 优先在**上一版行程**基础上只修正被指出问题的那几天，而不是每次都从最初候选池整体重建——这是修复过的一个真实问题（"三次复审等于重新生成三次行程"）。

修改是否真的"只改了该改的"由 `AgentResultAggregator._diff_itinerary` 校验：逐天比较 `model_dump()` 是否相等，划出 `preserved_days`/`changed_days`，如果用户要求"只改第 3 天"但检测到其他天也变了，会生成一条 warning 附在回复里，这是这套升级本身要保证的核心不变量。

---

## 5. 什么时候查本地 RAG，什么时候联网搜索？

`rag/source_decider.py::decide_source()`，规则表 + 关键词判定，**不用 LLM**：

- 命中"攻略/玩法/小众/避坑/怎么玩/本地人/私藏"等主观体验类关键词 → `RAG_ONLY`；
- 命中"天气/机票/汇率/营业时间/门票价格/签证政策"等强时效性关键词 → `WEB_ONLY`；
- 两者都命中 → `RAG_AND_WEB`；
- "我之前说过/我的偏好/我一直" → `MEMORY_ONLY`；
- 寒暄/闲聊（`GENERAL_CONVERSATION` 或"你好"这类问候）→ `NO_RETRIEVAL`；
- 兜底默认 `RAG_AND_WEB`（一个研究阶段的查询很少会因为同时拿到主观攻略和实时校验而受损）。

不接 LLM 兜底是刻意的：这是一个可枚举的五分类问题，规则表已经能覆盖，加 LLM 只增加延迟不增加准确度——和 `destination_intelligence/service.py`"已知表优先、LLM 只兜底未知目的地"是同一套设计哲学（开放式推理才值得用 LLM，枚举分类不需要）。

---

## 6. RAG 离线和在线流程分别是什么？

**离线（入库）**：`document_loader`（.docx/.md/.txt → 原始笔记）→ `cleaner`（去广告/去重复/去图片占位符）→ `canonicalization`（地名归一化，词典 + LLM 兜底）→ `semantic_chunker`（按段落/标题语义切块）→ `metadata_extractor`（关键词启发式 + 可选 LLM 富化生成 `activity_topics`/`travel_styles`）→ `embedding_writer`（算 embedding，按 `parent_document_id`/内容哈希判重后写入 `travel_guides` collection）。`ingestion_pipeline.py` 串联以上步骤，CLI 包装是 `scripts/ingest_travel_guides.py`。

**在线（检索）**：`source_decider` 决定要不要查 → `query_rewriter`（原始请求改写成 `semantic_query`/`keyword_queries`/`topic_filters`/正负偏好）→ `parallel_retriever`（dense/keyword/metadata/episodic/profile 五路并行，`asyncio.gather` + 每路走 `ToolManager` 超时熔断）→ `result_merger`（去重 + 融合打分 + 同源多样性 cap）→ `reranker`（LLM 多维判断或按融合分退化）→ `context_assembler`（拼成 `[USER PROFILE]`/`[EPISODIC MEMORY]`/`[TRAVEL GUIDE]`/`[LIVE WEB]` 四段文本，标注哪些内容涉及时间/价格需要实时验证）→ 喂给 Research Orchestrator Agent，不是把原始召回列表直接塞进 prompt。

---

## 7. 攻略文档如何切分，中文切分有哪些问题？

`rag/ingestion/semantic_chunker.py`：不按固定字符数切，按空行分段 + 标题/emoji 行识别语义边界（`target 400 / max 650 / overlap 80 tokens`，可配置）。一个短的单主题笔记保持一整块，长的多段笔记（比如"冲浪｜攀岩｜网球｜瑜伽"六件套笔记）在自己的段落/Day 边界处切开。

token 数用 `len(text)/1.5` 估算，**没有引入 tiktoken/transformers 分词器依赖**（项目里其他启发式模块也是这个风格），这个比例是中文场景下"大致 1-2 字符一个 token"的经验值，只用于分块粒度控制，不用于计费。

中文特有的坑：

1. 中文没有天然的词/句子长度基准，字符数估算 token 本身就是近似，不像英文按空格分词那样直观。
2. 小红书文案里 emoji（⭐️🏄🧘）经常被用作段落/主题的视觉分隔符而不是标点，所以标题识别的正则里专门加了一段 Unicode emoji 字符类，否则会漏掉这类自然的语义边界。
3. 中文音译地名一词多写非常普遍（"佩尼达岛"/"帕尼达岛"/"Nusa Penida" 指同一个地方），纯字符串匹配的检索会因为用词不一致而漏检，需要 `canonicalization.py` 做地名词典 + LLM 兜底的归一化，统一落到 `canonical_place_name`/`aliases` 字段。

---

## 8. ChromaDB 中存了什么，metadata 如何设计？

三个 collection **不混用**，共享同一个 `PersistentClient` 单例（`rag/chroma_client.py`，本地嵌入式，无需 Docker）：

| Collection | 内容 | 典型 metadata |
|---|---|---|
| `travel_guides` | 小红书攻略切块（`TravelGuideChunk`） | `canonical_destination`/`canonical_region`/`activity_topics`/`guide_type`/`source_type`/`freshness_level`/`quality_score` |
| `episodic_memory` | 压缩后的历史旅行事件 | `user_id`/`event_type`/`destinations` |
| `user_profile` | 带置信度的长期偏好陈述（一条陈述一条记录，不是一个用户一条 JSON） | `user_id`/`preference_dimension`/`status` |

设计要点：

- **Chroma metadata 只支持标量，不支持嵌套 list**——`activity_topics` 这种自由生成的标签列表要 `"|".join()` 存成扁平字符串才能建索引过滤，结构化版本另外存在 `content`/document 侧供检索后反序列化。
- **Embedding 模型默认 Chroma 内置 `ONNXMiniLM_L6_V2`**（本地 ONNX，免 API Key，离线可跑），下载失败会自动降级成自研的字符 n-gram 哈希 embedding（`HashEmbeddingFunction`，注册为 Chroma 的 `EmbeddingFunction` 以便跨进程重开集合），保证系统不因为模型下载失败而硬崩溃，代价是召回质量下降，`using_fallback_embedding()` 暴露给调用方感知当前是否在降级状态。
- **单例并发初始化有过真实的竞态 bug**（见问题 23），修复方式是显式双检锁而不是只靠 `@lru_cache`。

---

## 9. Hybrid Search、Query Rewrite、Rerank 分别解决什么问题？

- **Query Rewrite**（`rag/query_rewriter.py`）解决"用户原话不适合直接做向量检索"——口语化/带情绪的请求被改写成 `semantic_query`（语义查询）+ `keyword_queries`（关键词组合）+ `topic_filters`（主题过滤）+ 正负偏好；LLM 结构化输出，或退化成关键词表启发式，**用的是入库时 `metadata_extractor` 同一份 `topic_vocab`**，保证线上查询词表和入库 metadata 对得上，不会出现"查询词命中不了任何 filter"的错位。
- **Hybrid Search**（dense + keyword 并行）解决"纯向量检索会漏掉精确关键词命中但语义上不那么'像'的结果"——比如用户提到一个具体地名，keyword retriever 按子串命中数补充召回，弥补 embedding 相似度可能把它排低的问题；`retrieve_bm25()` 留了接口位但当前项目没引入真正的 BM25 索引，用命中计数做过渡方案。
- **Rerank**（`rag/reranker.py`）解决"融合分数是纯统计排序，不理解语义"——LLM 对每条候选逐条判断"是否直接回答需求/是否匹配目的地/是否符合偏好/是否可执行/是否重复/是否可能过时"，只保留真正有用的 `rerank_top_k` 条，"不要把全部召回内容直接塞进 Prompt"；无 LLM 时退化成按融合分数直接截断 top-K。

三者是漏斗的三个阶段：Rewrite 让查询更精确 → Hybrid 扩大召回覆盖面 → Rerank 收窄到真正有价值的证据。

---

## 10. 如何评价 RAG 的召回和最终回答质量？

**召回质量**：`scripts/eval_rag_retrieval.py` 跑 Recall@K / Precision@K / MRR / NDCG（离线评测集）。

**回答质量分两层，刻意不合并**：

1. **图内实时闸门**：`ReviewReport`（5 维：`time_feasibility`/`route_efficiency`/`preference_match`/`richness`/`budget`），`planner↔reviewer` 循环最多 3 次，`score>=85` 放行——要便宜、要快，是生成过程中的快速质量门。
2. **生成后深度评测**：`StrictTravelEvaluator`（`evaluation/llm_judge.py`），8 维加权求和（20/15/15/15/10/15/5/5=100）+ 9 条 `hard_penalties`（空的一天、重复推荐用户已拒绝内容、缺少活动说明、行程脱离目的地特色、漏掉用户明确要求的活动、时间冲突等）。硬扣分保证"不能因为格式完整就给高分"，不管 LLM 主观打分多高，客观可判定的失败模式一律强制扣分。

两者的输入范围也不同：早期的 `LLMJudge`（`judge.py`）只拿到 `user_request`+`expected_goal`+一段纯文本回复，**没法判断是否符合画像、是否遗漏用户明确要求的活动、是否错误改动了其他日期**；`StrictTravelEvaluator` 把输入扩展到 9 项（结构化需求/画像/情景记忆/目的地画像/候选活动/最终行程/工具证据/本轮反馈），全部来自 `AgentState` 已有字段，不需要额外查询就能做更准确的判断。

---

## 11. 工具调用的完整流程是什么？

统一收敛到 `tool_runtime/manager.py::ToolManager.call()`，所有 Agent **只允许通过这一个入口调用工具**，不允许直接 `.invoke()`：

1. **缓存检查**：`key=hash(tool_name + 归一化后的 kwargs)`，命中且未过期直接返回；
2. **熔断器检查**：该工具当前状态是 OPEN 就跳过调用，直接走 fallback 或返回降级结果；
3. **参数校验**：pydantic `args_schema`（LangChain `@tool` 自带的，或 registry 里手写的）校验 kwargs，不合法直接返回 `INVALID_PARAMETER`；
4. **超时执行**：`ThreadPoolExecutor(max_workers=1)` 包一层，`future.result(timeout=...)`；
5. **执行工具**：调用真正的工具函数；
6. **更新 metrics + 熔断器**：按工具自己返回的 `{"success": bool}` 业务级契约判定成功/失败（不是看有没有抛异常）；
7. **Fallback**：任何一步失败，如果调用方传了 `fallback()` 就用降级结果兜底。

所有工具约定统一返回 `{"success": bool, ...}` 或这样的 dict 列表，**从不 raise**，`ToolManager.call()` 在此基础上保持同样的返回形状，老代码按"读 success 字段"分支处理即可，不需要改调用方式。

---

## 12. 工具多时模型如何准确选择工具？

这个项目**不是"把所有工具都暴露给 LLM 做 function calling 自由选择"**的模式——工具选择的确定性主要由代码路由承担：Research Orchestrator 按目的地/兴趣/意图里的 `add_categories` 在代码里显式决定调用 Google Places / Weather / Visa / 小红书 / 攻略搜索里的哪几个，LLM 只负责工具内部参数（query 改写、topic 分类）。这样可以避免"工具描述写得不够精确导致 LLM 选错/漏选工具"这个经典 function-calling 痛点。

真正"开放式选择"的场景在 Stage-4 的 Skill Runtime（`skills/`）：每个 `SKILL.md` 通过 YAML frontmatter 声明 `synonyms`（关键词同义词）+ `query_templates` + 固定的 `tool` 字段（必须匹配 `tool_runtime/registry.py` 里的已知工具名），依然是**关键词匹配路由到 Skill**，而不是纯靠 LLM 在一堆工具描述里挑——同一套"规则优先，LLM 兜底"的项目哲学。

---

## 13. 外部工具超时、失败、返回异常怎么办？

三层都收敛在 `ToolManager.call()` 里（同问题 11）：

- **超时**：`ThreadPoolExecutor` + `future.result(timeout=tool_cfg.timeout_seconds)`；超时记录 metrics、触发熔断器失败计数，`executor.shutdown(wait=False)`——不等已经超时的线程收尾，避免慢调用拖慢主流程。
- **熔断**：手写约 60 行的 `CircuitBreaker`（没引入 `pybreaker`），per-tool 状态机 `CLOSED → OPEN（连续失败数超阈值）→ cooldown 后 HALF_OPEN（放一个探测请求）→ 成功回 CLOSED / 失败重新 OPEN`。熔断打开期间直接跳过真实调用，走 fallback 或返回"熔断中"的降级结果，避免对一个已知在挂的服务持续重试消耗资源。
- **业务级失败（工具正常返回但 `success: false`）**：这是本项目的核心约定——所有工具"从不 raise"，异常都被工具自己内部捕获转成 `{"success": false, "error": "..."}`；`ToolManager` 按这个业务字段（而不是 Python 异常）判定成功/失败，同样计入熔断器和 metrics。

三种失败模式最终都归一到同一个"读 `success` 字段做分支"的调用方契约，下游代码不需要写 `try/except` 去区分是超时、熔断还是业务失败。

---

## 14. 如何避免工具重复调用和 Agent 死循环？

**避免重复调用**：

- 短期/同参数重复：`CacheStore` 按 `(tool_name, 归一化 kwargs)` 的 TTL 缓存，`ToolManager.call()` 第一步就查缓存。
- 语义级重复：ingestion 阶段按 `(parent_document_id, chunk_index)` 或内容哈希判重（已存在则更新而非重复插入）；检索合并阶段 `result_merger._drop_near_duplicate_content` 用 `SequenceMatcher` 相似度 ≥0.9 判定近似重复，保留分数更高的一条。

**避免死循环**：项目里所有循环边都遵循同一个模式——"state 里的计数字段 + config 里的硬上限"：

- `reviewer ↔ planner`：`review_loop_count` / `max_review_loops`（默认 3）；
- `planner ↔ research_orchestrator`（可行性不足触发的补充搜索）：`max_research_expansion_loops`（默认 2）；
- `strict_evaluation ↔ planner`：`revision_round` / `max_revision_rounds`（默认 2），超预算后 `presentation_route()` 强制走 `final_output_with_notes`，"绝不挂起"。

超过上限一律强制放行到下一阶段（带上说明性标注），而不是抛异常或无限重试，保证用户侧永远能拿到一个结果。

---

## 15. 你的 Travel Agent 为什么响应慢，如何优化 P95？

延迟大头是**真实网络调用而非 LLM**：一次完整 Research（含小红书真实搜索）实测约 30 秒，主要是 Google Places/Routes 的真实网络往返（多标签搜索内部已并行，但单个标签内"搜索 + 详情"仍是几次真实请求）。

已经做的优化：

1. **LLM 侧**：排除掉不适合的 reasoning 模型（`deepseek-reasoner` 一次改写测出 6366 output token/约 70 秒），所有调用点固定 `tier="fast"`（`deepseek-chat`）；Requirement Agent 从"每轮要求 LLM 吐完整 JSON"改成"只吐 `{"updates": {...}}` 的增量 patch"，减小输出 token、加快单轮响应。
2. **架构侧**：`research_orchestrator` 做成"后台任务暂停点"（`execution/research_jobs.py`），配合 `interrupt_before`，`POST /chat` 不必阻塞整个 Research 过程；`POST /api/chat/stream` 用 SSE + `GET /api/research/status` 轮询，前端不用等一整轮完成。
3. **并行化**：Research 的 7 类 Worker 用 `ThreadPoolExecutor` 并行；RAG 的 5 路 retriever 用 `asyncio.gather` 并行。
4. **成本控制**：Activity Card 的 LLM 润色设了硬上限（`_MAX_LLM_CARD_ENRICHMENT=12` 条，按热度取前 N），不设上限时一次多标签搜索（20+ 候选）单次润色能跑到 90 秒以上，比整个并行 Research 还慢。

**已知未优化点**（如果面试官追问"还能怎么优化"，可以主动提）：Planner 阶段给每一个行程项单独调一次 Google Routes 目前是**串行**的，天数、每日景点数越多，这里的真实网络调用越多，这是下一个最直接的并行化目标；另外可以加一层"路线距离矩阵批量查询"来减少调用次数本身，而不只是并行。

---

## 16. 多个 Research 工具如何并行，哪些不能并行？

**能并行**：`ResearchOrchestratorAgent.run_full()` 用 `ThreadPoolExecutor` 并行跑 Google Places / 攻略搜索 / 小红书 / 签证 / 天气 / 路线 / 酒店这些**互相独立、没有数据依赖**的 Worker；RAG 的 5 路 retriever（dense/keyword/metadata/episodic/profile）用 `asyncio.gather` + `asyncio.to_thread` 并行——整个代码库是同步的，`asyncio.to_thread` 把 `ToolManager.call()` 这个阻塞调用包成协程，而不是给全代码库引入 asyncio 改造，`retrieve_all_sync()` 是给同步图调用的入口（内部 `asyncio.run(...)`）。

**不能/未并行**：

- **主链路串行**：Requirement → Research → Planner 有真实数据依赖（patch 后的偏好必须先到 Research，Research 的输出才能喂给 Planner），`AgentRouter` 的设计文档明确写了"没有可以有意义并行的地方"，需求文档提到的"partial parallel steps"在这版是 non-goal。
- **Planner 内部的路线查询**：目前对每个行程项单独调一次 Google Routes，是串行的（这版范围聚焦在 Research 阶段的并行化），是已知的性能优化点。

---

## 17. Redis、会话上下文和向量数据库分别存什么？

- **Redis**（`memory/redis_memory.py` 的 `SessionMemory` protocol，配置了 `REDIS_URL` 就用，否则进程内 dict 兜底）：存 L0 工作记忆 `WorkingMemory`（24h TTL，key=`travel:session:{id}:working_memory`，含 `recent_messages`/`current_intent`/`visible_candidates`/`pending_confirmation` 等）+ 旧版 L1 `ConversationMemoryRecord`（7 天 TTL，key 前缀不同，迁移期互不干扰）。
- **LangGraph Checkpointer**（当前 `MemorySaver`，进程内存）：按 `session_id`（=`thread_id`）存**完整的图执行状态快照**，是 `interrupt_before` 暂停/恢复机制的基础，语义上和上面的 Redis 会话记忆是两回事——一个是"图跑到哪了"，一个是"业务层面这个用户这次会话聊了什么/看到了什么候选"。
- **ChromaDB**（三个 collection，见问题 8）：`travel_guides` 是静态知识库（离线入库），`episodic_memory` 是**跨 session** 的历史旅行事件（用向量检索替代早期的 Jaccard 标签重叠，Chroma 不可用时降级回 Jaccard），`user_profile` 是带置信度状态机的长期偏好陈述（`SESSION_PREFERENCE → TENTATIVE_PROFILE → STABLE_PROFILE`）。

三者不能互相替代：Redis 存储的是"这一次会话"的短期状态，ChromaDB 存储的是"跨会话"的长期记忆，checkpointer 存储的是"图本身在哪个节点暂停、state 长什么样"。

---

## 18. 长对话如何压缩，如何避免丢失关键约束？

`WorkingMemory.recent_messages` 限制 `max_working_messages`（默认 12 条），超出先摘要再截断，摘要复用 Planner/Research 已有的"控制 prompt 长度"惯例，走 `get_llm(role=..., tier="fast")`。

但**关键约束不依赖"对话历史里还记得"来保证**——真正重要的信息在产生的当下就被提炼进结构化字段：`TravelRequirement`/`pending_confirmation`/`visible_candidates` 这些结构化状态本身就是"压缩后的关键事实"，Agent 读的是这些字段而不是重新解析原始对话文本。被用户明确拒绝过的候选会专门落进 episodic memory 的 `rejected_experiences`，这样即使对话历史被截断/摘要掉了，"不要重复推荐用户拒绝过的东西"这条约束依然能生效——Reviewer/StrictEvaluator 的 hard_penalty 里也有 `_check_repeated_rejected` 专门检测这种回归。

---

## 19. RAG 存在的情况下为什么仍然会幻觉？

几个真实存在的来源：

1. **主观攻略内容被当成客观事实**：小红书攻略里的"阿育吠陀油疗 60-90min"是作者的个人体验描述，不是官方营业信息，直接采信就是幻觉的温床。应对：`context_assembler.py` 专门标注 `needs_live_verification`，让 Research Agent 对含时间/价格的攻略内容做实时验证而不是直接采信为事实。
2. **结构化输出任务里 LLM 不完全遵守约束**：比如 Rerank 要求"chunk_id 必须原样复制，不要编造"，代码里仍然做了 `known_ids` 校验过滤掉 LLM 编造/改写过的 chunk_id 作为安全网，而不是完全信任 prompt 约束。
3. **降级路径的覆盖面天然有限**：heuristic 兜底只能识别文本里字面出现的关键词，LLM enrichment 能生成词表之外的新 topic 但也可能"生成"出原文没有的内容，所以设计成"追加"而不是"替换"关系——heuristic 结果始终保底存在，LLM 结果是锦上添花，不会因为 LLM 幻觉而丢失已知的可靠信息。
4. **有已知的、诚实标注的盲区**：`penalty_rules.py` 明确写了 `unsupported_claim`（编造不存在的事实）这条规则理论上该抓这类幻觉，但需要对真实世界事实做核查，heuristic 路径做不到，只有 LLM 评审路径能判断，代码注释里如实标注为"documented, not silently dropped"，没有假装已经解决。

---

## 20. 如何验证行程的时间、距离和预算合理性？

四层，刻意有重叠（因为服务不同的循环）：

1. **生成时就是确定性调度 + 真实数据**：Planner 每一次地点切换都真实调 `calculate_route`（Google Routes），不是 LLM 现算时间；LLM 只负责把 `reason` 文案写自然，不允许编造时间/费用/路线。
2. **`validator` 节点（规则硬校验）**：时间冲突、营业时间冲突、超预算、景点数量超标、重复景点、超过最晚返回酒店时间。
3. **`reviewer`（LLM 软性打分）**：`time_feasibility`/`route_efficiency` 是 5 维里的两维，结合硬规则给出的问题列表联合生成 `revision_instruction`。
4. **`strict_evaluation`（生成后深度评测）**：`penalty_rules.py::_check_schedule_overlap` 复现同款时间重叠检测，作为 `geographically_impossible` 的代理指标——不知道两地真实地理距离时，"排在一起的两个活动时间对不上"本身就是行程不可行的强信号；预算维度同样在 8 维打分里占权重。

四层重叠是有意的：`validator↔reviewer` 和 `strict_evaluation↔planner` 是两条独立的循环边，各自独立触发 revision，不共享检测结果，保证每条循环边自己就能闭环，不依赖另一条循环提前把问题修掉。

---

## 21. 如何设计 Agent 的端到端评测集？

分四层，各自独立、离线优先：

1. **意图层**：`intent_data/intent_examples.jsonl`（24 个意图 × 约 8 条正例/边界例）+ `feedback_examples.jsonl`（16 种反馈类型）+ `negative_examples.jsonl`（OOD 负例），`scripts/eval_intent_accuracy.py` 跑 Pattern+Embedding 准确率/Macro-F1（毫秒级、默认离线），`--with-llm` 可选加真实 LLM 路验证。
2. **检索层**：`scripts/eval_rag_retrieval.py` 跑 Recall@K/Precision@K/MRR/NDCG。
3. **端到端质量层**：`evaluation_cases/*.json`（feedback/destination/modification 三类，加上 Round-6 新增的 rag/memory/personalization/richness 类），配合 `LLMJudge`（人工用例 vs. Agent 真实回复的离线打分脚本 `scripts/eval_llm_judge.py`）。
4. **延迟层**：`scripts/eval_latency.py` 拆分 Fast/Deep Path 各路耗时，定位瓶颈在哪一路。

**测试套件本身也是"离线优先"哲学的一部分**：`pytest travel_agent/tests` 在 `tests/conftest.py` 里用 `monkeypatch` 在"HTTP/subprocess/LLM 调用边界"打桩——`stub_external_calls` 替换 6 个真实工具的 `.func` 为确定性假数据，`no_llm` 把所有 Agent 已绑定的 `get_llm` 引用都指到返回 `None`（注意：不能只 patch 模块属性，因为每个 Agent 文件是 `from ... import get_llm` 在 import 时就绑定了本地引用，需要逐个 Agent 模块 patch）。这保证 CI/开发环境全程离线、快速、不消耗真实 DeepSeek/Kimi/Google 额度，同时仍然覆盖真实的编排逻辑。

---

## 22. Badcase 如何采集、标注、归因和回流？

- **回流通道天然内建**：`intent_data/negative_examples.jsonl` 里，纠错样本以 `kind="correction"` + `review_status="pending"` 追加到同一个负例文件，**人工审核通过后才会被 `embedding_router` 采用**，避免未经确认的纠错样本直接污染检索样本库。
- **归因材料是结构化的**：每个 `IntentResult.evidence` 字段都带 `pattern`/`embedding`/`llm`/`workflow`/`fusion` 五路原始信号 + 融合过程（权重、agreement、惩罚项），一个 badcase 可以直接对着 `evidence` 字段判断是 Pattern/Embedding/LLM 哪一路给错了，还是 fusion 加权或 Workflow Validator 环节出的问题，不需要靠人工复现猜测。
- **评审失败自带归因标签**：`strict_evaluation` 的 `critical_failures` + `hard_penalty` 命中的具体 `rule` 字段（比如 `missed_explicit_activity`/`repeated_rejected_activity`）本身就是结构化的失败分类，不需要人工重新打标签。
- **诚实的欠缺**：目前没有一条"生产环境自动采集 badcase → 定期回流训练/调阈值"的管道——现状是研发阶段靠人工构造评测用例 + 人工审核负例文件，这是可以在"上线给大量用户"（问题 25）之后补的方向：比如把低分 `strict_evaluation` 结果或用户负反馈自动落库、定期人工抽样审核后并入 `negative_examples.jsonl`/评测集。

---

## 23. 讲一个你真实解决的线上或工程问题

三个可选故事，按"技术深度"从高到低：

**① ChromaDB 并发初始化竞态**：RAG 的 `parallel_retriever` 用 `asyncio.to_thread` 并行发起 5 路检索，意味着进程里第一次请求会有多个线程同时调 `get_collection()`。一开始只用 `@lru_cache` 做单例，**`@lru_cache` 本身不是"构造函数只执行一次"的线程安全保证**——多个线程可以同时 miss 缓存、同时进入构造逻辑。实测复现过 "Could not connect to tenant default_tenant" 报错，根因是多线程竞争初始化同一个 `PersistentClient` 路径。修复是加显式双检锁（`_client_lock`，先无锁判断再加锁二次判断）。这个问题的价值在于它是"看起来用了缓存装饰器就该线程安全"的一个常见误区。

**② 模型选型的实测反直觉**：一开始设想用 reasoning 模型（`deepseek-reasoner`）能提升行程理由润色的质量，实测一次 Activity Card 润色调用测得 **6366 个输出 token、约 70 秒**，且 `deepseek-reasoner` 不支持 `tool_choice`/函数调用（报错 "Thinking mode does not support this tool_choice"），完全不适合这类"受限输出、不需要多步推理"的任务。最终把所有调用点固定成 `tier="fast"`，`deep` tier 只留作预留接口——这体现了"先用真实调用测延迟/token，再决定要不要用更贵的模型"，而不是想当然地认为推理模型总是更好。

**③ 一个我这次会话里刚修的真实 bug**（如果面试官想听更"接地气"的例子）：Requirement Agent 用正则从"我想去东京玩"里抽目的地时，边界字符类没覆盖"玩"这种非标点结尾词，导致贪婪匹配成"东京玩"（多抓了一个字）。pytest 里一条多轮合并测试才暴露出来（`test_multi_turn_merge_preserves_previous_fields`）。修复是把边界匹配从"消费掉的字符类"换成正则 lookahead（`(?=[，,。\d]|玩|游|旅游|...|$)`），既能识别标点/数字边界，也能识别常见的中文结尾词而不把它们错误地并入实体本身。这类问题说明：**中文实体抽取的正则边界设计比看起来更容易漏边界情况，必须靠测试用例覆盖真实口语化表达才能发现。**

---

## 24. MCP 和直接 Tool Calling 有什么区别？

- **直接 Tool Calling**（本项目采用）：LLM 在同一进程内通过 function-calling 接口调用本地 Python 函数（LangChain `@tool`），工具的 schema/实现/权限都和 Agent 代码强耦合。优点是延迟低（进程内调用）、调试简单、类型安全（pydantic 直接校验参数）；缺点是工具集的扩展/替换需要改代码部署，跨语言/跨进程/跨团队复用困难。
- **MCP（Model Context Protocol）**：把"工具"抽象成一个独立的、进程外的 Server，通过基于 JSON-RPC 的标准协议暴露 tools/resources/prompts，Client（任何遵循协议的 Agent 框架）统一发现和调用。优点是工具实现语言无关、可以被多个不同的 Agent 应用复用、工具方可以独立部署升级不用改调用方代码；缺点是多一层进程间通信延迟，多一套协议契约要维护。

**本项目为什么没用 MCP**：所有第三方工具本质是自己写的 Python 封装（Google API 客户端、`opencli` 子进程、Agent Reach 子进程），加一层 `ToolManager` 中间件处理熔断/缓存/超时就够了，**没有"多个不同 Agent 应用需要共享同一套工具"的场景**——MCP 的核心收益（跨应用复用、独立升级）在单体应用里体现不出来，反而要多背一层协议开销。如果未来要把这些工具开放给别的团队/别的 Agent 复用，或者要接入现成的第三方 MCP Server（比如官方 Google Maps MCP），才是引入 MCP 的合适时机。

倒是 `skills/`（`SKILL.md` + YAML frontmatter + 文件热加载 `watcher.py`）这套设计解决了 MCP 试图解决的子问题之一——"能力可以不改代码就动态增删"，但用了更轻量的方式（进程内文件热加载 + mtime 指纹检测，不需要 `watchdog` 依赖，更不需要独立协议 Server）。

---

## 25. 如果把系统上线给大量用户，还需要补哪些能力？

1. **状态持久化换成共享存储**：当前 `MemorySaver`（LangGraph checkpointer）和 `research_jobs`（后台任务状态）都是**进程内内存**，单进程没问题，多进程/多副本部署下用户请求落到不同副本会"失忆"——必须换成 Redis/Postgres-backed checkpointer + 共享存储的任务状态。
2. **鉴权与多租户隔离**：当前 `session_id` 是调用方自己传的字符串，没有用户身份校验，生产环境需要加认证（JWT/OAuth）并按 `user_id` 做数据隔离（尤其是画像/情景记忆这类跨会话数据）。
3. **限流与配额**：Google Places/Routes/Weather/DeepSeek 都是按量计费的外部 API，当前的熔断器只防"单个工具连续失败"，不防"总体调用量爆炸"，需要按用户/租户加限流和配额控制。
4. **可观测性**：现有 `utils/logging.py`/`llm_logging.py` 是本地文本日志，生产环境要接入集中式 tracing（如 OpenTelemetry），把 `IntentResult.evidence` 这类调试信息、每次工具调用的延迟/成功率做成可按 `session_id`/`trace_id` 查询的链路追踪，而不是只在本地日志文件里。
5. **真正的持久化数据库**：`database_url` 预留了 SQLite/Postgres 配置但当前未接入任何持久化表，用户画像/情景记忆目前落在本地 JSON/JSONL 文件和单机 ChromaDB，多副本场景需要换成托管数据库和向量库（Chroma Server 模式或 Pinecone/Weaviate 等）。
6. **第三方依赖的服务端化**：小红书搜索依赖 `opencli` 驱动**用户本机**已登录的 Chrome，攻略搜索依赖用户本地安装的 Agent Reach——这两个假设了"有一台用户本机"，在服务端多用户场景下不成立，需要换成真正的服务端可用 API 或合规的爬虫/数据采购方案。
7. **生产级质量监控**：现有评测脚本都是离线批跑，需要加在线质量监控（比如抽样调用 `strict_evaluation` 或更轻量的实时指标）+ 低分自动告警，配合问题 22 提到的 badcase 自动采集回流管道，形成"上线后持续发现问题、持续修复"的闭环，而不是只在开发阶段人工构造用例。

---

*文档基于当前代码库（`travel_agent/` 全量模块 + `docs/round6_rag_memory_eval_design.md` 设计文档）梳理，回答时建议结合自己实际调试/踩坑的细节展开，会比背诵更有说服力。*
