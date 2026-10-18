import type { CandidatesPayload } from "../types"
import { TYPE_LABEL_CN } from "../lib/labels"

export default function CandidatesPanel({ candidates }: { candidates: CandidatesPayload }) {
  const groups = Object.entries(candidates.experiences ?? {})
  if (groups.length === 0) return null

  return (
    <div className="animate-fade-in-up rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-sm">
      <h3 className="mb-1 text-sm font-semibold text-[var(--text)]">候选体验</h3>
      <p className="mb-3 text-xs text-[var(--text-muted)]">
        在左侧聊天框里说出你想保留/去掉的项目，或直接说“帮我推荐”。
      </p>
      <div className="max-h-[420px] space-y-4 overflow-y-auto pr-1">
        {groups.map(([type, items]) => (
          <div key={type}>
            <div className="mb-1.5 text-xs font-semibold tracking-wide text-[var(--accent)] uppercase">
              {TYPE_LABEL_CN[type] ?? type} · {items.length}
            </div>
            <div className="space-y-2">
              {items.map((item) => (
                <div key={item.id} className="rounded-xl bg-[var(--surface-2)] p-2.5">
                  <div className="text-sm font-medium text-[var(--text)]">{item.name}</div>
                  {item.short_description && (
                    <div className="mt-0.5 text-xs text-[var(--text-muted)]">{item.short_description}</div>
                  )}
                  {item.rating > 0 && (
                    <div className="mt-1 text-xs text-[var(--text-muted)]">★ {item.rating.toFixed(1)}</div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
