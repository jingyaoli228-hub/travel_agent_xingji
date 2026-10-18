import type { ChatData, ChatResponse, DayPlan, HotelCandidate, InsertPreview, PlaceSearchResult, ResearchStatus, RouteSegment } from "../types"

export interface StreamEvent {
  type: "token" | "final"
  node?: string
  content?: string
  response?: string
  current_node?: string
  need_user_input?: boolean
  data?: ChatData
}

/**
 * Consumes `POST /api/chat/stream` (SSE). Calls `onToken` for every token
 * delta and resolves with the final event once the turn completes (either
 * because it ran fully synchronously, or because a research background job
 * was just dispatched -- see `travel_agent/api/chat_stream.py`).
 */
export async function postChatStream(
  sessionId: string,
  message: string,
  onToken: (content: string) => void,
): Promise<StreamEvent> {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  })
  if (!res.ok || !res.body) {
    throw new Error(`chat stream failed: ${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let finalEvent: StreamEvent | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let sepIndex: number
    while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, sepIndex)
      buffer = buffer.slice(sepIndex + 2)
      const line = block.split("\n").find((l) => l.startsWith("data: "))
      if (!line) continue
      const event = JSON.parse(line.slice("data: ".length)) as StreamEvent
      if (event.type === "token" && event.content) {
        onToken(event.content)
      } else if (event.type === "final") {
        finalEvent = event
      }
    }
  }

  if (!finalEvent) {
    throw new Error("chat stream ended without a final event")
  }
  return finalEvent
}

export async function getResearchStatus(sessionId: string): Promise<ResearchStatus> {
  const res = await fetch(`/api/research/status?session_id=${encodeURIComponent(sessionId)}`)
  if (!res.ok) throw new Error(`research status failed: ${res.status}`)
  return res.json()
}

export async function getSession(sessionId: string): Promise<ChatResponse> {
  const res = await fetch(`/api/session/${encodeURIComponent(sessionId)}`)
  if (!res.ok) throw new Error(`get session failed: ${res.status}`)
  return res.json()
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body?.detail?.code || body?.detail || `request failed: ${response.status}`)
  }
  return response.json() as Promise<T>
}

export const workspaceApi = {
  days: (tripId: string) => json<{ days: DayPlan[]; plan_version: number; hotel_selection_status: string; selected_hotels_by_city: Record<string, HotelCandidate> }>(`/api/trips/${tripId}/days`),
  routes: (tripId: string, dayId: string) => json<{ route_segments: RouteSegment[] }>(`/api/trips/${tripId}/days/${dayId}/routes`),
  search: (query: string, city: string) => json<{ results: PlaceSearchResult[] }>(`/api/places/autocomplete?q=${encodeURIComponent(query)}&city=${encodeURIComponent(city)}`),
  previewInsert: (tripId: string, dayId: string, body: Record<string, unknown>) => json<InsertPreview>(`/api/trips/${tripId}/days/${dayId}/preview-insert`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  applyPatch: (tripId: string, body: Record<string, unknown>) => json<{ status: string; updated_day_plan: DayPlan; updated_route_segments: RouteSegment[]; plan_version: number }>(`/api/trips/${tripId}/apply-patch`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  rollback: (tripId: string, body: Record<string, unknown>) => json(`/api/trips/${tripId}/rollback-patch`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  hotels: (tripId: string) => json<{ hotel_candidates_by_city: Record<string, HotelCandidate[]>; plan_version: number }>(`/api/trips/${tripId}/hotel-candidates`),
  selectHotel: (tripId: string, body: Record<string, unknown>) => json(`/api/trips/${tripId}/hotels/select`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
}
