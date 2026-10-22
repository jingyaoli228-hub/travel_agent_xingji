# 行迹微信小程序

这是原生微信小程序客户端，不依赖 React/Vite。当前 P0 体验版默认连接腾讯云 FastAPI、PostgreSQL、Redis 与 Chroma，并通过高德 Web Service、DeepSeek 和 RAG/Agent 完成任意国内城市的真实检索与规划；`local-api.js` 只保留为断网开发夹具，不再是体验版数据源。

## 本地预览

1. 打开微信开发者工具，导入本目录。
2. `project.config.json` 已配置当前项目的正式 AppID；如需更换主体，请同步替换为新主体的 AppID。
3. `config.js` 默认是 `transport: "remote"`，`apiBaseUrl` 必须是微信公众平台已登记的 HTTPS request 合法域名。
4. 本机忽略文件 `config.private.js` 可覆盖体验网关地址；不要在小程序包内保存服务器密钥。API 请求会通过 `wx.login` 向后端换取所有者短期令牌。

## 本地演示夹具

- `data/p0-demo.js`：北京 3 日行程、GCJ-02 地点、不同交通方式路线和本地点位目录。
- `utils/local-api.js`：与真实 REST API 同形的本地实现，覆盖规划、候选溢出、加地点、冲突预览、当天重算、撤销、复制、删除、小红书正文解析和 Agent 透视。
- 数据按行程拆成 `travel-agent:local-trip:<tripId>` 等多个 key；离线展示缓存继续使用 `travel-agent:trip:<tripId>:meta/day:*`，单 key 上限仍为 900KB。
- 仅当手动把 `transport` 改回 `local-demo` 时，首次启动才会种入北京 3 日演示行程。
- 从旧体验版升级到真实云端版时会定向清理 `p0-beijing-demo`，不会删除真实云端行程的离线缓存。

## 体验版与正式发布边界

- 生产 API 使用 `wx.login` + 后端 `code2session`，只签发给 `OWNER_OPENID` 的 12 小时令牌；行程接口同时校验 session 所有者。
- 配置微信 AppID/AppSecret、所有者 OpenID、签名密钥和稳定 HTTPS 域名后才能启用生产服务；并需在微信公众平台登记 HTTPS request 合法域名。
- 真实模式的 `apiBaseUrl` 不要带末尾 `/`。

## 已支持

- P10：空态、偏好轻确认、按天规划进度、装不下时的景点确认、质量草稿。
- 行程首页：原生地图、今天自动选中、分交通方式路线、三档抽屉、单一提醒位、质量徽标、玩法卡和对话撤销。
- 加地点：搜索、冲突卡、插入预览、只重算当天、强制加入显式标红。
- 我的行程：每次规划独立保存、历史不覆盖、已出行只读及复制为新行程。
- 小红书：仅粘贴正文解析与本地存储；不做在线搜索或爬取。
- Agent 透视：意图、L0-L3 记忆、工具、质量、变更和开发者记录。
