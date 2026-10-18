import { useState } from "react"
import type { InsertPreview, PlaceSearchResult } from "../types"

export function PoiInsertionDialog({ city, results, preview, busy, onSearch, onPreview, onApply, onCancel }: {
  city: string; results: PlaceSearchResult[]; preview?: InsertPreview; busy: boolean
  onSearch: (query: string) => void; onPreview: (place: PlaceSearchResult) => void; onApply: () => void; onCancel: () => void
}) {
  const [query, setQuery] = useState("")
  return <div className="fixed inset-0 z-50 grid place-items-center bg-black/35 p-4" role="dialog" aria-modal="true">
    <div className="max-h-[85vh] w-full max-w-xl overflow-y-auto rounded-2xl bg-[var(--surface)] p-5 shadow-2xl">
      <div className="mb-4 flex items-center justify-between"><div><h3 className="font-semibold">添加地点</h3><p className="text-xs text-[var(--text-muted)]">搜索范围：{city}</p></div><button onClick={onCancel}>✕</button></div>
      {!preview && <><form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); onSearch(query) }}><input value={query} onChange={(event) => setQuery(event.target.value)} className="min-w-0 flex-1 rounded-xl border border-[var(--border)] px-3 py-2" placeholder="搜索景点、餐厅、商店或活动" /><button className="rounded-xl bg-[var(--accent)] px-4 text-white" disabled={busy}>搜索</button></form>
      <div className="mt-4 space-y-2">{results.map((place) => <div key={place.place_id} className="flex items-start justify-between rounded-xl border border-[var(--border)] p-3"><div><div className="font-medium">{place.name}</div><div className="text-xs text-[var(--text-muted)]">{place.rating ? `★ ${place.rating} · ` : ""}{place.address}</div></div><button onClick={() => onPreview(place)} className="rounded-lg border border-[var(--accent)] px-3 py-1 text-sm text-[var(--accent)]">添加</button></div>)}</div></>}
      {preview && <div><h4 className="font-semibold">变更预览</h4>{preview.status === "INSERTION_CONFLICT" ? <div className="mt-3 rounded-xl bg-red-50 p-3 text-sm text-red-800">{preview.reason}</div> : <><div className="mt-3 space-y-2">{preview.changed_items?.map((change, index) => <div key={index} className="rounded-xl bg-[var(--surface-2)] p-3 text-sm">{String(change.action)}：{String(change.name || change.item_id)} {change.from ? `${String(change.from)} → ${String(change.to)}` : ""}</div>)}</div><div className="mt-4 flex justify-end gap-2"><button onClick={onCancel} className="rounded-xl border px-4 py-2">取消</button><button onClick={onApply} disabled={busy} className="rounded-xl bg-[var(--accent)] px-4 py-2 text-white">确认修改</button></div></>}</div>}
    </div>
  </div>
}
