import type { DayPlan, MapMarker, RouteSegment } from "../types"

export function idForDay(day: DayPlan) { return day.day_id || `day_${day.day_number}` }
export function markersForDay(day: DayPlan): MapMarker[] {
  return day.items.flatMap((item, index) => item.latitude != null && item.longitude != null ? [{
    itemId: item.item_id, placeId: item.place_id, name: item.name || item.location,
    type: item.activity === "hotel" ? "hotel" : ["breakfast", "lunch", "dinner", "restaurant"].includes(item.activity) ? "restaurant" : "attraction",
    latitude: item.latitude, longitude: item.longitude, sequence: index + 1,
  }] : [])
}
export function insertionSlots(day: DayPlan): Array<string | null> { return [null, ...day.items.map((item) => item.item_id)] }
export function replaceOneDay(days: DayPlan[], dayId: string, replacement: DayPlan): DayPlan[] {
  return days.map((day) => idForDay(day) === dayId ? replacement : day)
}
export function routesForDay(routeMap: Record<string, RouteSegment[]>, selectedDayId: string): RouteSegment[] {
  return routeMap[selectedDayId] || []
}
