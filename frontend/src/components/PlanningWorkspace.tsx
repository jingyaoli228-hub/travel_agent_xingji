import { useCallback, useEffect, useMemo, useState } from "react"
import { workspaceApi } from "../api/client"
import type { DayPlan, HotelCandidate, InsertPreview, MapMarker, PlaceSearchResult, RouteSegment } from "../types"
import ChatInput from "./ChatInput"
import MessageBubble from "./MessageBubble"
import { PoiInsertionDialog } from "./PoiInsertionDialog"
import { WorkspaceMap } from "./WorkspaceMap"
import type { ChatMessage } from "../types"
import { idForDay, markersForDay } from "../lib/workspaceState"

const dayId = idForDay

export function PlanningWorkspace({ tripId, initialDays, messages, isBusy, onSend }: {
  tripId: string; initialDays: DayPlan[]; messages: ChatMessage[]; isBusy: boolean; onSend: (text: string) => void
}) {
  const [days, setDays] = useState(initialDays)
  const [selectedDayId, setSelectedDayId] = useState(dayId(initialDays[0]))
  const [selectedItemId, setSelectedItemId] = useState<string>()
  const [routes, setRoutes] = useState<RouteSegment[]>([])
  const [version, setVersion] = useState(1)
  const [insertAfter, setInsertAfter] = useState<string | undefined | null>(null)
  const [searchResults, setSearchResults] = useState<PlaceSearchResult[]>([])
  const [preview, setPreview] = useState<InsertPreview>()
  const [busy, setBusy] = useState(false)
  const [hotels, setHotels] = useState<Record<string, HotelCandidate[]>>({})
  const [selectedHotels, setSelectedHotels] = useState<Record<string, HotelCandidate>>({})
  const day = days.find((entry) => dayId(entry) === selectedDayId) || days[0]

  useEffect(() => { workspaceApi.days(tripId).then((result) => { setDays(result.days); setVersion(result.plan_version); setSelectedHotels(result.selected_hotels_by_city || {}) }).catch(() => undefined) }, [tripId])
  useEffect(() => { if (selectedDayId) workspaceApi.routes(tripId, selectedDayId).then((result) => setRoutes(result.route_segments)).catch(() => setRoutes([])) }, [tripId, selectedDayId, version])
  useEffect(() => { workspaceApi.hotels(tripId).then((result) => { setHotels(result.hotel_candidates_by_city); setVersion(result.plan_version) }).catch(() => undefined) }, [tripId])

  const markers = useMemo<MapMarker[]>(() => [
    ...markersForDay(day),
    ...(hotels[day.city || ""] || []).map((hotel, index) => ({ itemId: `hotel:${hotel.place_id}`, placeId: hotel.place_id, name: hotel.name, type: "hotel", latitude: hotel.latitude, longitude: hotel.longitude, sequence: index + 1 })),
  ], [day, hotels])
  const selectItem = useCallback((id: string) => setSelectedItemId(id), [])

  async function search(query: string) { setBusy(true); try { setSearchResults((await workspaceApi.search(query, day.city || "")).results) } finally { setBusy(false) } }
  async function makePreview(place: PlaceSearchResult) {
    setBusy(true); try { setPreview(await workspaceApi.previewInsert(tripId, selectedDayId, { place_id: place.place_id, insert_after_item_id: insertAfter || null, preferred_duration_minutes: 90, user_locked: true, current_plan_version: version, request_id: crypto.randomUUID() })) } finally { setBusy(false) }
  }
  async function applyPreview() {
    if (!preview?.patch_id) return
    setBusy(true); try {
      const result = await workspaceApi.applyPatch(tripId, { patch_id: preview.patch_id, plan_version: version, request_id: crypto.randomUUID() })
      setDays((current) => current.map((entry) => dayId(entry) === selectedDayId ? result.updated_day_plan : entry)); setRoutes(result.updated_route_segments); setVersion(result.plan_version); closeInsert()
    } finally { setBusy(false) }
  }
  function closeInsert() { setInsertAfter(null); setSearchResults([]); setPreview(undefined) }
  async function selectHotel(city: string, hotel: HotelCandidate) {
    setBusy(true); try {
      const result = await workspaceApi.selectHotel(tripId, { city, place_id: hotel.place_id, plan_version: version, request_id: crypto.randomUUID() }) as { days: DayPlan[]; plan_version: number; selected_hotels_by_city: Record<string, HotelCandidate> }
      setDays(result.days); setVersion(result.plan_version); setSelectedHotels(result.selected_hotels_by_city)
    } finally { setBusy(false) }
  }

  return <div className="workspace-grid flex-1 overflow-hidden">
    <section className="workspace-chat"><div className="flex-1 space-y-3 overflow-y-auto p-3">{messages.map((message) => <MessageBubble key={message.id} message={message} />)}</div><ChatInput onSend={onSend} disabled={isBusy || busy} /></section>
    <section className="workspace-itinerary">
      <div className="flex gap-2 overflow-x-auto border-b border-[var(--border)] p-3">{days.map((entry) => <button key={dayId(entry)} onClick={() => { setSelectedDayId(dayId(entry)); setSelectedItemId(undefined) }} className={`min-w-28 rounded-xl px-3 py-2 text-left text-xs ${selectedDayId === dayId(entry) ? "bg-[var(--accent)] text-white" : "bg-[var(--surface-2)]"}`}><strong>{entry.date || `Day ${entry.day_number}`}</strong><div>{entry.city}</div><div>{entry.is_cross_city ? "跨城日" : entry.status || "行程日"}</div></button>)}</div>
      <div className="flex-1 overflow-y-auto p-4"><div className="mb-3 flex justify-between text-sm"><strong>{day.city} · {day.accommodation || "酒店待选择"}</strong><span>当日预算 ¥{day.items.reduce((sum, item) => sum + item.estimated_cost, 0).toFixed(0)}</span></div>
        <div className="grid h-9 place-items-center"><button aria-label="在第一项前添加地点" onClick={() => setInsertAfter("")} className="h-7 w-7 rounded-full border border-dashed border-[var(--accent)] text-[var(--accent)]">＋</button></div>
        {day.items.map((item, index) => <div key={item.item_id}><button onClick={() => selectItem(item.item_id)} className={`w-full rounded-xl border p-3 text-left ${selectedItemId === item.item_id ? "border-[var(--accent)] bg-[var(--accent-soft)]" : "border-[var(--border)] bg-[var(--surface)]"}`}><div className="flex justify-between"><span><b>{item.time}</b> · {item.name || item.location}</span>{item.user_locked && <span title="用户锁定">🔒</span>}</div><div className="mt-1 text-xs text-[var(--text-muted)]">{item.transport} · {item.duration_minutes} 分钟 · ¥{item.estimated_cost}</div></button><div className="grid h-9 place-items-center"><button aria-label={`在${index + 1}项后添加地点`} onClick={() => setInsertAfter(item.item_id)} className="h-7 w-7 rounded-full border border-dashed border-[var(--accent)] text-[var(--accent)]">＋</button></div></div>)}
        {Object.entries(hotels).map(([city, candidates]) => selectedHotels[city] ? null : <div key={city} className="mt-4"><h3 className="mb-2 font-semibold">请选择 {city} 酒店</h3><div className="space-y-2">{candidates.slice(0, 6).map((hotel) => <div key={hotel.place_id} onClick={() => setSelectedItemId(`hotel:${hotel.place_id}`)} className={`w-full rounded-xl border p-3 text-left ${selectedItemId === `hotel:${hotel.place_id}` ? "border-[var(--accent)]" : "border-[var(--border)]"}`}><b>{hotel.name}</b><div className="text-xs text-[var(--text-muted)]">{hotel.rating ? `${hotel.rating} 分 · ${hotel.user_rating_count || 0} 条评价` : "暂无评分"} · {hotel.estimated_price ? `${hotel.estimated_price.minimum || ""} ${hotel.estimated_price.currency}` : "实时价格待确认"}</div><div className="text-xs text-[var(--text-muted)]">客房规则：{hotel.room_rules_verified ? "已验证" : "unknown"}</div><button onClick={(event) => { event.stopPropagation(); selectHotel(city, hotel) }} className="mt-2 rounded-lg bg-[var(--accent)] px-3 py-1 text-xs text-white">选择该酒店</button></div>)}</div></div>)}
      </div>
    </section>
    <section className="workspace-map"><WorkspaceMap markers={markers} routes={routes} selectedItemId={selectedItemId} onSelect={selectItem} version={version} /></section>
    {insertAfter !== null && <PoiInsertionDialog city={day.city || "当前城市"} results={searchResults} preview={preview} busy={busy} onSearch={search} onPreview={makePreview} onApply={applyPreview} onCancel={closeInsert} />}
  </div>
}
