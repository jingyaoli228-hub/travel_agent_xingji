import type { ResearchStatus } from "../types"

const WORKER_LABELS: Record<string, string> = {
  amap_places: "景点 / 餐厅（高德地点搜索）",
  routes: "交通路线（高德路线规划）",
  weather: "天气预报",
  xiaohongshu: "小红书攻略",
  web_guides: "大众攻略",
  visa: "签证信息",
  hotels: "酒店推荐",
}

const ORDER = ["amap_places", "routes", "weather", "xiaohongshu", "web_guides", "hotels", "visa"]

function WorkerRow({ name, status }: { name: string; status: "running" | "done" | undefined }) {
  return (
    <div className="flex items-center gap-2.5 py-1.5 text-sm">
      {status === "done" ? (
        <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-[var(--success)] text-[11px] text-white">✓</span>
      ) : status === "running" ? (
        <span className="h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-[var(--accent-soft)] border-t-[var(--accent)]" />
      ) : (
        <span className="h-5 w-5 shrink-0 rounded-full border-2 border-dashed border-[var(--border)]" />
      )}
      <span className={status === "done" ? "text-[var(--text)]" : "text-[var(--text-muted)]"}>
        {WORKER_LABELS[name] ?? name}
      </span>
    </div>
  )
}

export default function ResearchProgressPanel({ status }: { status: ResearchStatus | null }) {
  if (!status) return null

  const workers = Array.from(new Set([...ORDER, ...Object.keys(status.progress)]))

  return (
    <div className="animate-fade-in-up rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-sm">
      <h3 className="mb-2 text-sm font-semibold text-[var(--text)]">正在搜索</h3>
      <div>
        {workers.map((name) => (
          <WorkerRow key={name} name={name} status={status.progress[name]} />
        ))}
      </div>
      {status.status === "error" && (
        <p className="mt-2 text-xs text-[var(--danger)]">{status.error ?? "搜索出现错误"}</p>
      )}
    </div>
  )
}
