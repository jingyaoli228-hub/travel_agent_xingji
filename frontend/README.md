# AI Travel Planner — Frontend

React + Vite + TypeScript + TailwindCSS 前端，配合 `../travel_agent` FastAPI 后端使用。

## 启动

```bash
npm install
npm run dev
```

打开 http://localhost:5173。开发模式下 `/api`、`/chat` 会被 Vite 代理到
`http://localhost:8000`（见 `vite.config.ts`），所以需要先在项目根目录启动后端：

```bash
uvicorn travel_agent.main:app --reload --port 8000
```

## 结构

```
src/
├── pages/
│   ├── LandingPage.tsx     # 首页：输入目的地 -> 跳转到 /chat
│   └── ChatPage.tsx        # 聊天页：消息流 + 需求状态卡 + 搜索进度 + 候选/行程
├── components/             # 消息气泡、输入框、需求状态卡、搜索进度、候选列表、行程卡片
├── hooks/useChatSession.ts # 会话状态：SSE 流式接入 + Research 后台任务轮询
├── api/client.ts           # postChatStream / getResearchStatus / getSession
└── types.ts                # 与后端 ChatResponse/TravelRequirement/... 对应的 TS 类型
```

会话 ID 保存在 `localStorage`（`travel-agent:session-id`），刷新页面不会丢失当前对话；点击
"新对话"会生成新的会话 ID。

候选体验的选择（"去掉XX"/"我要XX、YY"/"帮我推荐"）沿用后端现有的对话式交互，没有单独的
选择 API——侧边栏的候选列表只是只读展示，方便对照聊天内容。
