import type { ChatData } from "../types"

const STAGE_LABELS: Record<string, string> = {
  requirement: "需求收集中",
  clarification: "需求收集中",
  region_confirmation: "区域确认中",
  confirmation: "等待确认",
  research: "正在搜索",
  researching: "正在搜索",
  selection: "选择体验",
  planning: "生成行程中",
  review: "行程审核中",
  done: "行程已完成",
  post_plan_feedback: "行程反馈中",
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5 text-sm">
      <span className="shrink-0 text-[var(--text-muted)]">{label}</span>
      <span className="truncate text-right font-medium text-[var(--text)]">{value}</span>
    </div>
  )
}

export default function RequirementStatusCard({ data }: { data: ChatData }) {
  const req = data.travel_requirement
  const stage = data.stage
  const stageLabel = (stage && STAGE_LABELS[stage]) || stage || "—"

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[var(--text)]">旅行需求</h3>
        <span className="rounded-full bg-[var(--accent-soft)] px-2.5 py-0.5 text-xs font-medium text-[var(--accent)]">
          {stageLabel}
        </span>
      </div>

      {!req ? (
        <p className="text-sm text-[var(--text-muted)]">告诉我你的目的地和大致计划吧。</p>
      ) : (
        <div className="divide-y divide-[var(--border)]">
          {req.destination && <Row label="目的地" value={req.destination} />}
          {req.departure_city && req.departure_city !== "未指定" && (
            <Row label="出发地" value={req.departure_city} />
          )}
          {(req.duration_days || req.start_date) && (
            <Row
              label="出行时间"
              value={[req.start_date, req.duration_days ? `${req.duration_days} 天` : null]
                .filter(Boolean)
                .join(" · ")}
            />
          )}
          {req.num_travelers != null && <Row label="人数" value={`${req.num_travelers} 人`} />}
          {req.budget != null && (
            <Row label="预算" value={`${req.budget.toLocaleString()} ${req.budget_currency ?? "CNY"}`} />
          )}
          {req.pace && <Row label="节奏" value={req.pace} />}
          {req.interests?.length > 0 && <Row label="兴趣" value={req.interests.join("、")} />}
          {req.experience_preferences?.length > 0 && (
            <Row label="细分偏好" value={req.experience_preferences.join("、")} />
          )}
          {req.region_preferences?.length > 0 && (
            <Row label="区域安排" value={req.region_preferences.join("、")} />
          )}
        </div>
      )}
    </div>
  )
}
