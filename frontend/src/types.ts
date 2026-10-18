export type Stage =
  | "requirement"
  | "clarification"
  | "region_confirmation"
  | "confirmation"
  | "research"
  | "researching"
  | "selection"
  | "planning"
  | "review"
  | "done"
  | "post_plan_feedback"
  | string

export interface TravelRequirement {
  departure_city?: string | null
  destination?: string | null
  start_date?: string | null
  end_date?: string | null
  duration_days?: number | null
  num_travelers?: number | null
  budget?: number | null
  budget_currency?: string
  pace?: string | null
  interests: string[]
  experience_preferences: string[]
  region_preferences: string[]
  constraints: string[]
  confirmed: boolean
}

export interface Source {
  title: string
  url: string
  source_type: string
  snippet?: string | null
}

export interface TravelExperience {
  id: string
  name: string
  type: string
  category: string
  location: string
  region?: string | null
  rating: number
  popularity: number
  popularity_level: "mainstream" | "niche"
  duration_minutes: number
  cost: number
  currency: string
  best_time?: string | null
  opening_hours?: string | null
  short_description: string
  detailed_description: string
  why_recommended: string[]
  highlights: string[]
  drawbacks: string[]
  reservation_required?: boolean | null
  source: Source
}

export interface CandidatesPayload {
  experiences: Record<string, TravelExperience[]>
}

export interface ItineraryItem {
  item_id: string
  place_id?: string | null
  time: string
  activity: string
  location: string
  transport?: string | null
  duration_minutes: number
  estimated_cost: number
  reason: string
  region?: string | null
  city?: string | null
  item_type?: string | null
  name?: string | null
  latitude?: number | null
  longitude?: number | null
  user_locked?: boolean
  source?: "planner" | "user_added" | "hotel_selection" | "transport"
  place_details_status?: string
}

export interface DayPlan {
  day_id?: string | null
  day_number: number
  date?: string | null
  items: ItineraryItem[]
  city?: string | null
  accommodation?: string | null
  is_day_trip?: boolean
  is_cross_city?: boolean
  status?: string | null
}

export type TravelMode = "WALK" | "TRANSIT" | "DRIVE" | "BICYCLE" | "FERRY" | "FLIGHT"
export interface RouteSegment {
  segment_id: string
  from_item_id: string
  to_item_id: string
  travel_mode: TravelMode
  duration_minutes: number
  distance_meters?: number | null
  encoded_polyline?: string | null
  polyline?: { lat: number; lng: number }[]
  status: "REAL_ROUTE" | "FALLBACK" | "UNAVAILABLE"
  warning?: string | null
}

export interface HotelCandidate {
  place_id: string; name: string; address: string; latitude: number; longitude: number; city: string
  rating?: number | null; user_rating_count?: number | null; photos: string[]
  map_uri?: string | null; distance_to_transit_meters?: number | null
  average_route_minutes_to_pois?: number | null; estimated_price?: { minimum?: number; maximum?: number; currency: string } | null
  price_source?: string | null; room_rules_verified: boolean; room_rules: Record<string, string>
}

export interface MapMarker {
  itemId: string; placeId?: string | null; name: string; type: string; latitude: number; longitude: number
  sequence: number; status?: string
}

export interface PoiInsertionState { afterItemId?: string; query: string; results: PlaceSearchResult[]; preview?: InsertPreview }
export interface PlaceSearchResult { place_id: string; name: string; address?: string; rating?: number; location?: { lat: number; lng: number }; types?: string[] }
export interface InsertPreview { status: string; patch_id?: string; updated_day_plan?: DayPlan; updated_route_segments?: RouteSegment[]; changed_items?: Record<string, unknown>[]; plan_version: number; reason?: string; alternatives?: Record<string, unknown>[] }

export interface PlanningWorkspaceState {
  selectedDate: string; selectedDayId: string; selectedItemId?: string
  dayPlan: DayPlan; markers: MapMarker[]; routeSegments: RouteSegment[]
  hotelSelections: Record<string, HotelCandidate>; insertionState?: PoiInsertionState
  isMapLoading: boolean; isReplanning: boolean; planVersion: number
}

export interface Itinerary {
  days: DayPlan[]
}

export interface BudgetBreakdown {
  flights: number
  hotels: number
  attractions: number
  food: number
  transport: number
  shopping_buffer: number
  total: number
  currency: string
}

export interface HotelOption {
  name: string
  area: string
  star_rating?: number | null
  price_per_night?: number | null
  price_source?: string | null
  rating: number
  highlights: string[]
}

export interface TravelPlan {
  overview: string
  itinerary: Itinerary
  map_route_summary: string
  budget: BudgetBreakdown
  hotel_suggestions: HotelOption[]
  transport_suggestions: string[]
  notes: string[]
  sources: Source[]
}

export interface ReviewReport {
  score: number
  [key: string]: unknown
}

export interface ChatData {
  stage?: Stage
  travel_requirement?: TravelRequirement
  candidates?: CandidatesPayload
  selected_places?: { experiences: TravelExperience[] }
  itinerary?: Itinerary
  review_report?: ReviewReport
  final_plan?: TravelPlan
  [key: string]: unknown
}

export interface ChatResponse {
  response: string
  current_node: string
  need_user_input: boolean
  data: ChatData
}

export type WorkerStatus = "running" | "done" | undefined

export interface ResearchStatus {
  status: "idle" | "running" | "done" | "error"
  progress: Record<string, WorkerStatus>
  error?: string | null
}

export interface ChatMessage {
  id: string
  role: "user" | "assistant"
  content: string
  streaming?: boolean
}
