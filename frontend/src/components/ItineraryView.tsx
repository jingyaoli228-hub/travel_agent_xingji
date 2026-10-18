import type { DayPlan, TravelPlan } from "../types"
import { ACTIVITY_LABEL_CN } from "../lib/labels"

function DayCard({ day }: { day: DayPlan }) {
  const total = day.items.reduce((sum, i) => sum + i.estimated_cost, 0)
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-sm">
      <div className="mb-3 flex items-baseline justify-between">
        <h4 className="text-sm font-semibold text-[var(--text)]">
          Day {day.day_number}
          {day.date ? <span className="ml-2 font-normal text-[var(--text-muted)]">{day.date}</span> : null}
        </h4>
        {total > 0 && <span className="text-xs text-[var(--text-muted)]">预计花费 ¥{total.toFixed(0)}</span>}
      </div>
      <ol className="relative space-y-4 border-l border-[var(--border)] pl-4">
        {day.items.map((item, i) => (
          <li key={i} className="relative">
            <span className="absolute top-1 -left-[21px] h-2 w-2 rounded-full bg-[var(--accent)]" />
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="text-sm font-semibold text-[var(--text)]">{item.time}</span>
              <span className="rounded-full bg-[var(--accent-soft)] px-2 py-0.5 text-[11px] font-medium text-[var(--accent)]">
                {ACTIVITY_LABEL_CN[item.activity] ?? item.activity}
              </span>
              <span className="text-sm font-medium text-[var(--text)]">{item.location}</span>
            </div>
            <p className="mt-1 text-sm text-[var(--text-muted)]">{item.reason}</p>
            <div className="mt-1 flex gap-3 text-xs text-[var(--text-muted)]">
              <span>{item.duration_minutes} 分钟</span>
              {item.estimated_cost > 0 && <span>约 ¥{item.estimated_cost.toFixed(0)}</span>}
              {item.transport && <span>{item.transport}</span>}
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}

export function ItineraryDays({ days }: { days: DayPlan[] }) {
  return (
    <div className="space-y-4">
      {days.map((day) => (
        <DayCard key={day.day_number} day={day} />
      ))}
    </div>
  )
}

export function FinalPlanSummary({ plan }: { plan: TravelPlan }) {
  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-sm">
        <h3 className="mb-2 text-sm font-semibold text-[var(--text)]">行程概览</h3>
        <p className="text-sm whitespace-pre-wrap text-[var(--text-muted)]">{plan.overview}</p>
        <div className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
          {Object.entries({
            交通: plan.budget.transport,
            住宿: plan.budget.hotels,
            景点: plan.budget.attractions,
            餐饮: plan.budget.food,
            机票: plan.budget.flights,
            弹性: plan.budget.shopping_buffer,
          }).map(([label, value]) => (
            <div key={label} className="rounded-xl bg-[var(--surface-2)] px-3 py-2">
              <div className="text-xs text-[var(--text-muted)]">{label}</div>
              <div className="font-medium text-[var(--text)]">
                {value.toLocaleString()} {plan.budget.currency}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-2 text-sm font-semibold text-[var(--text)]">
          预算合计：{plan.budget.total.toLocaleString()} {plan.budget.currency}
        </div>
      </div>
      <ItineraryDays days={plan.itinerary.days} />
    </div>
  )
}
