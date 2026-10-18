import { useState } from "react"
import { useNavigate } from "react-router-dom"

export default function LandingPage() {
  const [destination, setDestination] = useState("")
  const navigate = useNavigate()

  const start = () => {
    navigate("/chat", { state: { initialMessage: destination.trim() } })
  }

  return (
    <div className="relative min-h-screen overflow-hidden bg-[var(--canvas)]">
      <div
        className="pointer-events-none absolute inset-0 opacity-60"
        style={{
          background:
            "radial-gradient(60% 50% at 50% 0%, var(--accent-soft) 0%, transparent 70%)",
        }}
      />

      <header className="relative mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <div className="flex items-center gap-2 text-[15px] font-semibold text-[var(--text)]">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-[var(--accent)] text-white">✈</span>
          AI Travel Planner
        </div>
        <button
          onClick={() => navigate("/chat")}
          className="rounded-full border border-[var(--border)] px-4 py-1.5 text-sm text-[var(--text-muted)] transition hover:border-[var(--accent)] hover:text-[var(--text)]"
        >
          直接进入对话 →
        </button>
      </header>

      <main className="relative mx-auto flex max-w-3xl flex-col items-center px-6 pt-20 pb-32 text-center">
        <span className="mb-5 inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-1 text-xs font-medium text-[var(--text-muted)]">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--success)]" /> 4 个协作 Agent · 实时数据 · 秒级响应
        </span>

        <h1 className="text-4xl font-semibold tracking-tight text-[var(--text)] sm:text-5xl">
          告诉我你的旅行计划
        </h1>
        <p className="mt-4 max-w-xl text-balance text-lg text-[var(--text-muted)]">
          说出目的地、天数、预算和喜好，我会帮你搜集真实资料、规划每日行程，并随时根据你的反馈调整。
        </p>

        <div className="mt-10 w-full max-w-xl">
          <div className="flex items-center gap-2 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-2 shadow-sm transition focus-within:border-[var(--accent)] focus-within:shadow-md">
            <input
              autoFocus
              value={destination}
              onChange={(e) => setDestination(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && start()}
              placeholder="我要去哪里？例如：10 月想去巴厘岛玩 5 天…"
              className="flex-1 bg-transparent px-3 py-2.5 text-[15px] text-[var(--text)] outline-none placeholder:text-[var(--text-muted)]"
            />
            <button
              onClick={start}
              className="shrink-0 rounded-xl bg-[var(--accent)] px-5 py-2.5 text-[15px] font-medium text-white transition hover:bg-[var(--accent-hover)]"
            >
              开始规划
            </button>
          </div>
        </div>

        <div className="mt-16 grid w-full grid-cols-1 gap-4 sm:grid-cols-3">
          {[
            { title: "真实数据源", desc: "高德地点 / 路线 / 天气 / 小红书实时搜索" },
            { title: "多轮对话式规划", desc: "随时补充或修改需求，Agent 增量理解" },
            { title: "逐日行程卡片", desc: "含理由、亮点、预计花费的完整行程展示" },
          ].map((f) => (
            <div
              key={f.title}
              className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5 text-left shadow-sm"
            >
              <div className="text-sm font-semibold text-[var(--text)]">{f.title}</div>
              <div className="mt-1 text-sm text-[var(--text-muted)]">{f.desc}</div>
            </div>
          ))}
        </div>
      </main>
    </div>
  )
}
