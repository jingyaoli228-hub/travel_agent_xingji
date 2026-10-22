# P0 实施说明

本文件逐轮记录《PRD v2》P0 的实现结果。每轮分别说明代码位置和用户可见的功能变化；只有代码链路完成后才更新 PRD 状态。

## 第 1 轮：质量底线与国内黄金回归

### 代码改动

- `travel_agent/agents/research_agent.py`：调整 `ResearchOrchestratorAgent.auto_select`，把必去和排除、兴趣相关性、区域覆盖、可信度、评分、热度与类型多样性纳入候选排序。
- `travel_agent/graph/nodes.py`：将用户明确排除地点传入候选自动选择。
- `evaluation_cases/domestic_golden_cases.json`：新增北京、上海、成都、西安、杭州、南京、重庆、广州、苏州、厦门共 10 个回归案例。
- `travel_agent/evaluation/domestic_golden.py`、`scripts/eval_domestic_golden.py`：新增离线黄金案例评估器和命令行入口。
- `travel_agent/tests/test_domestic_golden.py`、`travel_agent/tests/test_research_agent.py`：覆盖十城质量门槛、偏好排序、必去和排除。
- `README.md`：补充回归命令和输出说明。

### 功能变化

自动推荐会优先保留用户明确要求、过滤明确排除项，并提高符合兴趣且分布更合理的候选。十城离线回归可在不调用地图或 LLM 服务的情况下重复运行。

### 验收记录

2026-10-22：10/10 案例通过，Reviewer 最低分 95、平均分 95，偏好候选比例平均 100%。完整 pytest 曾报告 358 项通过、1 项与本轮改动无关的行程追加反馈用例失败；排除该既有失败后 358 项通过。

## 第 2 轮：偏好轻确认与研究并行

### 代码改动

- `miniprogram/pages/planning/index.js`、`miniprogram/pages/planning/index.wxml`：偏好页提供兴趣、节奏、作息 chips，固定的必去/不想去输入，以及条件式候选选择。
- `travel_agent/api/chat.py`：保留只返回偏好维度的规划上下文接口，并新增研究预热接口及状态查询。
- `travel_agent/execution/research_prefetch.py`：新增 Redis/RQ 生产任务与本地线程开发任务；研究结果短期缓存，并支持状态读取。
- `travel_agent/graph/nodes.py`：初始研究节点优先复用预热结果；按确认后的排除项过滤，并补齐预热结果中缺失的必去地点。预热失败时回退到原研究流程。
- `miniprogram/utils/api.js`：新增 `prefetchResearch` API 客户端。
- `travel_agent/tests/test_api_endpoints.py`、`travel_agent/tests/test_p0_preference_flow.py`：覆盖预热接口、结果复用和确认后排除。

### 功能变化

用户确认目的地信息并进入偏好页时，后台即开始准备目的地候选。用户选择 chips 的时间与研究重叠；点击确认后使用已有研究结果做排序和筛选。偏好仍会写回行程需求，必去和排除仍以最终确认值为准。

### 验收记录

2026-10-22：规划上下文、偏好预热、结果复用和工作流相关用例 15 项通过；其中 API/偏好/工作流命令输出为 15 passed（后续静态页面契约单独验证时为 11 passed）。

## 第 3 轮：地图优先行程页

### 代码改动

- `miniprogram/pages/itinerary/index.wxml`：主页面使用原生地图、三档抽屉、按天标签、节点卡片、质量入口和固定对话栏；地图点击与地图 POI 点击都进入加点页。
- `miniprogram/pages/itinerary/index.js`：按当前天计算地图标记和路线，标记包含地点顺序及酒店/餐厅类型，路线按交通方式渲染；加入当天所有点位的 `includePoints` 供地图自动缩放。
- `miniprogram/components/xj-bottom-sheet/`：提供 peek、half、full 三档抽屉交互。
- `travel_agent/tests/test_miniprogram_p0_contracts.py`：固定地图、标记、路线、天切换、抽屉与对话栏关键契约。

### 功能变化

打开行程后以地图为主视图。切换日期会更新该天的点位和路线并调整地图视野；点击标记或行程卡片可聚焦地点卡片；从地图底图点击位置可进入加点流程。离线状态显示本地行程画布。

### 验收记录

2026-10-22：静态页面契约及此前相关用例命令通过 11 项。原生微信地图的设备手势和不同基础库表现仍需在微信开发者工具/真机做最终交互验收。

## 第 4 轮：地图加点、排序预览与冲突处理

### 代码改动

- `travel_agent/workspace/service.py`：新增 `preview_reorder`，校验版本、地点集合与锁定项，计算重排后的路线/时间，检测晚间和超时冲突，并生成待应用 patch；`apply_patch` 使用 patch 中的操作摘要记录历史。
- `travel_agent/api/workspace.py`：新增 `POST /trips/{trip_id}/days/{day_id}/preview-reorder`。
- `miniprogram/utils/api.js`、`miniprogram/utils/local-api.js`：新增远程和本地排序预览适配。
- `miniprogram/pages/itinerary/index.js`、`index.wxml`、`index.wxss`：拖动后先恢复原列表并展示自定义预览面板，列出逐点时间、路线时长/状态和冲突；用户确认才调用 `applyPatch`，取消则不修改行程，版本冲突会刷新最新行程；应用后可通过现有撤销入口回退。
- `miniprogram/pages/add-place/index.js`：加点继续使用既有 `preview-insert → apply-patch` 流程，冲突保留替代动作。

### 功能变化

排序和加点都遵循预览、确认、应用的步骤。排序时先展示新顺序、逐点时间及路线估算/实况；可能过晚时显示冲突说明，由用户决定是否应用。成功应用的排序写入版本历史，可撤销。

### 验收记录

2026-10-22：最终定向测试覆盖排序预览契约和服务端重排行为；36 项中 35 项首轮通过，发现并修正一项旧提醒优先级断言，复跑结果见收尾记录。

## 第 5 轮：手动编辑锁定并写入 L1

### 代码改动

- `miniprogram/pages/add-place/index.js`：手动加点的预览请求设置 `user_locked: true`；`miniprogram/utils/local-api.js` 同步尊重该字段。
- `travel_agent/workspace/service.py`：排序预览识别被移动的节点并自动锁定；旧版直接重排接口也会锁住顺序发生变化的节点，避免绕过预览 API 时丢失用户锁定。
- `travel_agent/schemas/memory.py`、`travel_agent/memory/conversation_memory.py`、`travel_agent/memory/memory_manager.py`：记忆记录新增 `last_user_edits`，保留最近 20 次编辑摘要。
- `travel_agent/api/workspace.py`：应用、锁定、删除、撤销后把最新行程同步回 LangGraph，并将摘要、变更节点和 plan_version 写入 L1 与图状态。
- `travel_agent/graph/nodes.py`：Planner 把最近的手动编辑作为修订上下文，并把锁定节点保留在原日期/顺序。

### 功能变化

手动加点或拖动排序后节点自动加锁。用户下次要求 Agent 修改行程时，锁定节点不会被移到别的日期或改写；透视面板可以看到此前的手动编辑摘要。用户仍可显式解锁。

### 验收记录

2026-10-22：实现已落地；未运行新增测试。

## 第 6 轮：短回复与行程差异高亮

### 代码改动

- `travel_agent/execution/schemas.py`、`travel_agent/execution/result_aggregator.py`：聚合结果增加 `changed_items`，按节点 ID/名称比较前后行程并产生 ADD/UPDATE/REMOVE 条目。
- `travel_agent/graph/nodes.py`：初始规划回复只给状态、天数、预算摘要；无 Reviewer 结果时明确标“质量状态未知”，并把改动范围写入 `latest_diff`。
- `travel_agent/api/chat.py`、`travel_agent/api/workspace.py`：SSE/普通对话和行程 overview 暴露同一份 `latest_diff`。
- `miniprogram/pages/itinerary/index.js`、`index.wxml`、`index.wxss` 与 `components/xj-day-tabs/`：对话页显示新增/删除/调整条目和提醒；发生变化的日期标签高亮。

### 功能变化

规划完成或用户要求修改后，对话不再重复贴出整份每日行程；地图画布仍是完整行程的查看入口。对话面板会集中显示本次变化、受影响日期和冲突提醒。

### 验收记录

2026-10-22：实现已落地；未运行新增测试。

## 第 7 轮：质量真实性与单提醒优先级

### 代码改动

- `travel_agent/api/workspace.py`：只有 Reviewer 明确 `passed=true` 才报告通过；strict 分数不能替代 Reviewer 通过标志。无 Reviewer 时质量状态为 `unknown`，已定状态也不会由分数单独推断。
- `miniprogram/components/xj-quality-badge/`、`miniprogram/pages/itinerary/`：增加未知态，不再把缺数据画成 0 分失败；徽标分数在未知时显示“—”。
- `miniprogram/components/xj-alert-bar/index.js`：统一服务降级、天气/客流风险、质量草稿和一般信息的优先级；风险提醒可占地图顶部提醒位。

### 功能变化

用户看到“通过”意味着 Reviewer 实际通过；没有评审记录会显示“未知”，有评分但未通过会显示草稿。降级、天气/客流和质量告警共用一个优先显示位，其余提醒折叠，不会堆叠多个横幅。

### 验收记录

2026-10-22：实现已落地；未运行新增测试。

## 第 8 轮：微信自用认证、健康恢复和告警

### 代码改动

- `travel_agent/api/auth.py`：新增 `/api/auth/wechat`，以微信 `code2session` 换取 OpenID，仅匹配配置的所有者后签发 12 小时 HMAC-SHA256 令牌。
- `travel_agent/config/settings.py`、`.env.example`：增加微信 AppID/AppSecret、OWNER_OPENID、AUTH_TOKEN_SECRET、健康告警 webhook 与 Cloudflare Tunnel 配置；生产环境缺少必要身份配置会拒绝启动。
- `travel_agent/main.py`：除登录与健康检查外，所有 API 需携带所有者令牌；增加数据库/Redis/Chroma readiness 轮询，状态转为 degraded 时向可选 webhook 告警，恢复后可再次触发告警。
- `travel_agent/persistence/database.py`、`travel_agent/api/workspace.py`、`chat.py`、`chat_stream.py`：以令牌身份覆盖客户端 user_id，并逐 session 校验行程所有权。
- `miniprogram/utils/api.js`、`app.js`、`config.js`：通过 `wx.login` 获取短期令牌并缓存；移除小程序包里的共享体验密钥请求头。
- `miniprogram/config.private.js`（本机忽略文件）：移除旧共享体验凭证，只保留 API 地址，避免旧密钥随小程序模块打包；文件仍不纳入 Git。
- `compose.yaml`：API/gateway readiness 返回 503 时由 Docker healthcheck 识别；加入 autoheal 监视器和带健康检查的服务；可选 `public` profile 启动 Cloudflare Tunnel。
- `scripts/preflight_public_deploy.py`、`.env.example`：发布前要求微信所有者凭证、长签名密钥、Tunnel token、HTTPS 公网 API origin、告警 webhook；核对小程序私有配置的 API 地址一致，拒绝临时 trycloudflare 域名及遗留共享 `trialAccessKey`。错误只显示字段名/配置原因，不回显密钥。
- `miniprogram/README.md`：说明小程序 HTTPS 合法域名和真实密钥配置要求。

### 功能变化

微信登录后只有配置的本人 OpenID 可获得访问令牌；猜测 trip_id 或改写 user_id 不能访问他人会话。依赖服务不健康时容器状态会进入 unhealthy 并由 autoheal 重启，恢复异常可通过 webhook 告警。Tunnel 提供公网 HTTPS 转发入口。

### 验收记录与上线前配置

2026-10-22：代码和配置模板已落地，但生产上线尚未完成。再次只读探测确认公网 `/health/ready` 为 200，而 `/api/auth/wechat` 仍返回旧体验版凭证错误；`.env` 中微信、所有者 OpenID、签名、Tunnel 和告警配置均缺失，当前机器无 Docker，仓库中没有实际腾讯云主机地址（部署手册仍为 `SERVER_IP` 占位符），SSH 配置中的主机也不是旅行 Agent 服务。未向未知主机写入或部署。新增发布前预检，防止缺密钥、临时域名或小程序/API 域名不一致时误启动公网 profile。后续仍需正确服务主机/部署入口及生产凭证，才能做线上部署和手机端验收。

## 第 9 轮：Agent 透视数据完善

### 代码改动

- `travel_agent/api/workspace.py`：透视接口增加真实/估算路线分段、候选数、已有工具调用记录、最近编辑摘要、行程 ID；不再把整段聊天条数冒充 L1 编辑数。
- `miniprogram/pages/agent-insight/index.wxml`：分别展示路线降级、L1 编辑和工具记录。

### 功能变化

透视页显示的是当前行程实际持久化的状态；不存在的耗时/缓存命中数据不会伪造。L1 数字现在指手动编辑数量，并能查看最近编辑内容。

## 第 10 轮：小红书粘贴导入与来源追踪

### 代码改动

- `travel_agent/api/workspace.py`：解析导入文本中的 URL，保存到数据库导入记录，并将来源链接写入 RAG 知识块；索引失败时明确返回错误。
- `travel_agent/persistence/database.py`：新增仅按登录用户读取最近导入记录的接口函数；`GET /api/imports/xhs` 返回个人导入素材。
- `miniprogram/utils/api.js`、`local-api.js`：增加个人导入列表适配和本地演示记录。
- `miniprogram/pages/itinerary/index.js`：根据地点将本人导入的笔记来源补到对应玩法卡。

### 功能变化

用户从剪贴板粘贴笔记正文/链接，确认地点后可存入个人知识库；导入链接保留并会在相同地点的玩法卡中出现。来源没有成功索引时会明确报错，不再静默忽略。

## 第 11 轮：玩法卡与北京 20 点预置

### 代码改动

- `miniprogram/data/beijing-top20-playcards.js`：保留 20 个北京地点的个性化理由、推荐动线、必看/可跳过、避坑、时长和来源状态字段。
- `miniprogram/pages/itinerary/index.js`、`index.wxml`：节点卡展开玩法详情；只对实际导入且带链接的笔记显示“看原笔记”，静态预置卡不会把小红书主页伪装成原笔记。
- `travel_agent/api/workspace.py`：导入的来源 URL 可以随知识块返回。

### 功能变化

地点卡能展开到推荐玩法与子节点；“出来之后”根据当前行程中该地点之后的下一站及路线动态生成，最后一站则给出返住处/休息提示。资料明确区分预置建议和用户原始笔记。没有可追溯链接时不显示虚假的来源按钮；用户导入过同地点笔记后可以复制其原链接。

## 第 12 轮：独立行程历史与权限边界

### 代码改动

- `travel_agent/api/workspace.py`、`travel_agent/persistence/database.py`：按登录所有者筛行程列表，并校验 trip 读取、删除、复制和透视权限；状态根据行程日期及真实 Reviewer 结果确定。
- `miniprogram/pages/trips/`：保留“我的行程”、新建/切换/删除、状态展示和按 trip 查看对话的既有流程。

### 功能变化

每次规划仍在独立 session/trip 下保存，对话与行程绑定。状态为草稿、已定、已出行；行程已出行可只读查看或复制成新行程。

## 第 13 轮：行程及玩法卡离线缓存

### 代码改动

- `miniprogram/utils/trip-cache.js`：缓存行程元数据、对话摘要、路线/天计划分片、差异和玩法卡；单 key 限 900KB，总量目标 8MB，空间不足时先淘汰最久未用的旧行程缓存。
- `miniprogram/pages/itinerary/index.js`：断网时读取本地行程与玩法卡，保持只读。

### 功能变化

弱网或离线时可查看最近同步行程、路线及北京预置攻略，不会因旧行程缓存耗尽本地配额而静默覆盖当前行程。

## 第 14 轮：天气/客流风险地图提示

### 代码改动

- `travel_agent/api/workspace.py`：从最终计划提醒中提取天气、风险、客流、排队等内容并进入统一提醒列表。
- `miniprogram/components/xj-alert-bar/index.js`、`miniprogram/pages/itinerary/index.wxml`、`index.wxss`：风险为最高非服务降级优先级，显示在地图顶部单一提示位；其余提醒折叠在同一横幅。

### 功能变化

当行程有天气或人流/排队风险时，地图上方优先提示风险，不会阻止用户继续规划；严重服务降级仍优先显示。

## 收尾记录

2026-10-22：定向 P0 pytest 共 40 passed（认证令牌、发布预检正反例〔含拒绝旧共享凭证〕、工作区预览/重排/撤销、前端静态契约、偏好预热、十城黄金回归与 API）。`python scripts/preflight_public_deploy.py --env-file .env` 在当前真实环境按预期失败，只列出缺失字段且不回显值。另执行 Python 语法编译、小程序 JS 语法检查及 `git diff --check`。微信开发者工具/真机交互仍待验收；生产手机入口未部署，见第 8 轮及 PRD 状态。全量测试未在本轮重跑。

## 第 15 轮：开发者工具编译兼容与上线追查

### 代码改动

- `miniprogram/pages/itinerary/index.wxml`：地图、离线画布、无行程空态由跨组件 `wx:if / wx:elif / wx:else` 分支改为三个互斥的 `wx:if` 条件，避免当前微信开发者工具版本将 `wx:else` 判定为脱离 `wx:if`。

### 功能变化

地图在线、离线/只读画布及空态的互斥展示条件不变；开发者工具现可正常编译并显示小程序首页。此修复只恢复开发预览，不代表服务器登录问题已解决。

### 验收记录与线上状态

2026-10-22：微信开发者工具模拟器重新编译成功并显示行迹首页。定向 P0 测试本次运行 11 passed。全量 `python -m pytest -q` 为 333 passed、29 skipped、2 failed、5 errors；失败/错误集中在现有 `test_post_plan_feedback.py` 的响应断言以及当前环境缺少 `chromadb` 导致的 RAG/记忆测试导入错误。`git diff --check` 通过。尚未成功上传小程序体验版，也未提交审核或发布正式版；开发者工具中误开了 Git 仓库提示，未初始化该目录，也未产生外部写入。公网登录仍由旧体验凭证拦截，服务器部署仍缺可验证的腾讯云实例入口及生产环境配置。

### 继续部署所需的最小条件

腾讯云服务器入口已从历史发布记录找回，无需用户再找 IP/SSH 用户。当前只缺独立小程序账号的 AppSecret 和本人 OpenID；这两项需从微信公众平台/本人微信登录流程取得。随机 `AUTH_TOKEN_SECRET` 可由部署时生成，Tunnel token 或固定域名仅在要替换现有临时 TryCloudflare 通道时需要。微信开发者工具/公众平台自动化在本轮被物理 Escape 中断；未上传新体验包、未写远端文件，也未重启当前服务。旧体验版和运行中的后端保持原状。

## 部署入口恢复记录（2026-10-22）

回查此前已完成的发布任务后，纠正上一段的初步判断：本项目正式小程序 AppID 是 `wx3e3c60840720f755`，之前的体验版已成功发布至 `0.9.5`；腾讯云登录入口与容器均可用（具体 SSH 地址和本机密钥路径不写入公开仓库）。`/opt/travel-agent/current` 指向既有 P0 bugfix release；正在运行的 Compose 容器仍引用旧版本。未查看或回显服务器 `.env` 的秘密内容，仅按字段名核对；新自用登录所需 `WECHAT_APP_ID`、`WECHAT_APP_SECRET`、`OWNER_OPENID`、`AUTH_TOKEN_SECRET`、稳定 HTTPS/Tunnel 配置当前均未配置。旧体验版由共享体验凭证保护，而本轮代码已切换为 `wx.login` + 所有者 OpenID，因此不能直接把新前端上传到旧后端，否则请求会失败。未上传 0.9.6，未写远端文件、未重启服务。后续先按旧凭证兼容模式部署体验预览，再单独完成 OpenID 安全 P0。

## 公众平台会话续查（2026-10-22）

用户确认已登录微信公众平台后，尝试读取当前 `mp.weixin.qq.com` 标签并通过本机浏览器窗口确认账号。当前浏览器连接无法可靠绑定/确认标签 URL，计算机操作工具按安全策略中止本轮 UI 操作；没有重新登录、输入或读取 AppSecret，也没有取得本人 OpenID。重新运行本地 `scripts/preflight_public_deploy.py --env-file .env`，仅报告缺少的字段名：`WECHAT_APP_ID`、`WECHAT_APP_SECRET`、`OWNER_OPENID`、`AUTH_TOKEN_SECRET`、`CLOUDFLARE_TUNNEL_TOKEN`、`PUBLIC_API_BASE_URL`、`HEALTH_ALERT_WEBHOOK_URL`，未回显任何值。未上传小程序、未向云端发送秘密、未改动或重启线上服务；线上仍保持旧的可用版本。下一次需在浏览器控制可用时继续从当前已登录页面读取独立小程序配置，并在真正写入前确认敏感凭证的目标云主机。

## GitHub 与上次体验版发布链路核对（2026-10-22）

### 查证结果

- `origin` 是 `jingyaoli228-hub/travel_agent_xingji`，本地 `main` 与 `origin/main` 同在 `6594983`（2026-10-20，`fix(P0 02-05): repair real planning and itinerary editing`）。该 GitHub 提交包含上次体验版使用的旧客户端/后端链路；但本轮 P0 代码目前是本地未提交工作区改动，尚不在 GitHub `main` 上。
- GitHub `miniprogram/config.js` 从被 `.gitignore` 忽略的 `miniprogram/config.private.js` 读取 API 地址和 `trialAccessKey`；`miniprogram/utils/api.js` 通过 `X-Xingji-Trial-Key` 请求腾讯云。这套已发布链路使用体验凭证，不依赖微信 AppSecret/OpenID。`project.config.json` 指向独立行迹 AppID `wx3e3c60840720f755`。
- 历史提交 `ffb8590` 为无域名本地体验构建，`8730e02` 随后将体验构建切至真实云端 API 与忽略文件中的体验凭证；PRD 技术说明记录 0.9.4 手机端真实云端验证，先前发布任务记录确认后来成功上传 0.9.5。GitHub 仓库没有 `.github` 自动上传工作流；微信体验版上传是通过本机已登录的微信开发者工具 CLI 完成。
- 本轮本地 P0 改动明确删除客户端 `trialAccessKey`，改为 `wx.login` + 服务端 `/api/auth/wechat` + 所有者 OpenID/HMAC token，并令 production 后端必须配置 AppSecret 与所有者 OpenID。此改变正是“上次可直接上传、这次必须先配新后端”的原因；之前把它笼统描述为上传本身被 AppSecret 卡住，不准确。上传命令仍可用，但当前本机私有配置只有 API 地址、缺旧体验凭证；而按当前新代码上传到仍运行旧后端也会因登录 API 不存在/旧凭证拦截而无法工作。

### 代码/功能影响与当前结论

此轮只核对了 GitHub、本地 Git 历史与差异，没有写 GitHub、没有更改任何小程序或云端服务，也没有上传。DevTools CLI `islogin` 返回 `login: true`。核对后的正确发布路径是为体验版显式提供旧凭证兼容模式；该体验版本身不等于 P0 的“仅本人 OpenID 鉴权”完成。

## 体验版兼容发布准备（2026-10-22）

### 代码改动

- `travel_agent/config/settings.py`、`travel_agent/main.py`：增加默认关闭的 `LEGACY_TRIAL_AUTH_ENABLED` 显式开关。production 只有在该开关与服务端 `TRIAL_ACCESS_KEY` 同时存在时才允许临时预览；新微信鉴权配置若只填了一部分仍拒绝启动。兼容模式会记录警告，API 仍校验体验凭证。
- `miniprogram/config.js`、`miniprogram/utils/api.js`：从本机忽略配置读取 `authMode`/体验凭证；仅显式选 `trial` 且提供本机凭证时发送旧请求头，默认仍为 `wechat` + Bearer。凭证不进入 Git 源码。
- `scripts/preflight_public_deploy.py`：增加 `--legacy-trial-preview`，预览模式仍检查 HTTPS 地址一致、两侧凭证存在和显式开关；允许当前 TryCloudflare 地址，但输出明确提示这不是所有者 OpenID 鉴权。标准生产预检继续拒绝共享体验凭证。
- `.env.example`、`docs/xingji-p0/deployment.md`：记录过渡开关与安全边界，注明体验凭证会随包发送、仅适用于受限体验成员，不能将该项标为安全 P0 完成。

### 功能变化与验证

新旧认证流程可由私有本机配置明确切换：旧凭证模式可让新版界面/功能连接现有体验后端；默认仍使用新微信 OpenID 登录，不会悄悄降级。定向测试 `python -m pytest -q travel_agent/tests/test_trial_access.py travel_agent/tests/test_deployment_preflight.py travel_agent/tests/test_auth.py travel_agent/tests/test_miniprogram_p0_contracts.py`：11 passed。此处仅为兼容代码准备；尚未把体验凭证复制到客户端、部署服务器、提交 GitHub 或上传体验版。

## 体验版实际部署记录（2026-10-22）

### 本轮代码与部署改动

- 已部署包含 P0 更新的后端代码至新的服务器 release，并原子切换 `/opt/travel-agent/current`；新 release 的 `runtime`、`data` 继续复用现有持久化目录，未重建数据库或清理用户数据。仅更新并重启 API、worker、gateway、autoheal 容器，Postgres、Redis、Chroma 与隧道容器保持原状。
- `scripts/package_for_server.ps1` 现在从服务器包中排除 `miniprogram/config.private.js`、`project.private.config.json` 等本机私有配置，并检查归档中没有这些文件，避免把体验凭证随后端发布包发送。
- 微信体验构建使用被 Git 忽略的本机 `miniprogram/config.private.js`：指向当前 HTTPS API，并显式设为 `authMode: "trial"`。配置中含有服务器既有共享体验凭证，因此不记录在文档或仓库；此凭证仅用于微信受限体验成员访问，不是个人身份鉴权。

### 功能变化与验证

- 小程序新界面与 P0 行程规划、行程编辑、离线缓存及风险提示功能已随微信开发者工具 CLI 上传为 `0.9.6`，上传描述为“P0体验版更新：行程规划、交互优化与风险提示”。CLI 使用行迹 AppID `wx3e3c60840720f755`，结果为 `√ upload`；该操作上传体验版，不是提交审核或发布正式版。
- 服务器 Compose 状态检查显示 API、gateway、worker、autoheal 健康；`http://127.0.0.1:8080/health/ready` 返回 HTTP 200。鉴权探针在无凭证时返回 401；使用服务器现有体验凭证时请求通过鉴权并进入 API 路由（该探针请求因缺少业务参数返回 422），证明体验版的兼容访问路径可用。
- 本机定向 P0 测试此前 35 项通过；此前收尾记录的定向套件为 40 passed。此处未重跑全量测试。构建期间 npm 提示存在依赖审计告警（3 moderate、6 high），本轮未自动升级依赖。
- 本轮代码和上述部署安全修正已推送 GitHub `main`，最新提交 `13f98e1`。`config.private.js` 和体验凭证没有提交。

### 必须保留的安全边界

当前 `0.9.6` 是通过显式旧体验凭证兼容模式连接线上后端。小程序包内的共享体验凭证可被体验包成员提取，因此仅可用于受限体验成员，不能当作正式发布的个人身份安全控制。P0 中“微信登录并以本人 OpenID 限制访问”仍未完成；在取得并配置独立小程序 AppSecret、本人 OpenID 和正式鉴权密钥后，应切换回默认 `wechat` 模式并重新部署/上传。当前版本也继续使用既有临时 HTTPS 隧道；尚未完成固定域名迁移或正式提审。

## 体验反馈修复：作息、滚动、必去与路线多样性（2026-10-22）

### 代码改动位置

- `miniprogram/pages/planning/index.wxml`、`index.js`、`index.wxss`：作息选项改用页面原生点击控件，不再依赖自定义 chip 的事件转发；明确显示早起 07:00、正常 08:30、晚起 10:00，并将所选时间作为结构化“起床时间”发送。必去候选在选择清单中不可被误点排除。
- `travel_agent/agents/requirement_agent.py`：无论离线规则还是 LLM 增量解析，都以用户界面明确提交的时钟时间为准，避免 LLM 忽略“早起/晚起”选项。
- `miniprogram/components/xj-bottom-sheet/index.wxml`：列表滚动不再要求先把抽屉拖至全屏；仅正在执行排序手势时暂停普通滚动。
- `travel_agent/agents/research_agent.py`：城市覆盖搜索将每条片区查询绑定回片区信息，并使用“杭钢”到“杭州钢铁”别名辅助必去 POI 识别、候选排序和保留。
- `travel_agent/agents/planner_agent.py`：规划前抽出明确必去 POI，确保它们占用每日景点槽位之前先排入行程；必去点按行程日分布，必要时不会因每日普通景点上限被静默丢弃。对未要求用户分区的城市行程，按研究到的不同片区分配每日候选。午/晚餐从当天片区候选优先选择，并按上一地点坐标挑选更近的餐厅。
- 回归用例分别加入 `travel_agent/tests/test_miniprogram_p0_contracts.py`、`test_requirement_agent.py`、`test_planner_partial_replan.py`。

### 功能变化

1. 早起、正常、晚起三项可以直接点选，规划请求明确带上 07:00、08:30 或 10:00。
2. 行程列表在抽屉半屏时也能上下滑；拖动抽屉仍由把手完成，排序手势期间才暂时禁用列表滚动。
3. 研究到的必去景点（包括“杭钢公园”与正式地点名“杭州钢铁…”的匹配）排在普通候选之前，并纳入真实日程，不只停留在候选列表。
4. 城市研究结果保留片区归属，避免每一天都从同一处候选池拿景点；餐厅依当天活动的坐标择近，减少跨天或单日路线出现远距离餐馆的情况。

### 验证与限制

定向回归 54 passed，包含作息规则/LLM 路径、必去点安排、跨片区日程、邻近餐厅、研究候选、预览鉴权和小程序静态契约；Python 编译、`node --check miniprogram/pages/planning/index.js`、`git diff --check` 均通过。pytest 有两条依赖版本警告，不影响结果。区域和距离优化依赖高德返回的地点片区及坐标；如果数据源本身没有坐标，餐厅会按同片区/原候选顺序回退，不能承诺精确距离。此版仍沿用体验凭证兼容模式，只能作为微信受限体验版，不等同正式 OpenID 鉴权或正式发布。
