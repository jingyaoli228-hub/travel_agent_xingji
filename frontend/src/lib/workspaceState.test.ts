import { describe, expect, it } from "vitest"
import type { DayPlan, RouteSegment } from "../types"
import { insertionSlots, markersForDay, replaceOneDay, routesForDay } from "./workspaceState"

const item = (id: string, latitude?: number, longitude?: number) => ({ item_id: id, time: "10:00", activity: "attraction", location: id, duration_minutes: 60, estimated_cost: 0, reason: "", latitude, longitude })
const day = (number: number, items = [item(`item-${number}`, 30 + number, 120 + number)]): DayPlan => ({ day_id: `day_${number}`, day_number: number, city: "Tokyo", items })

describe("planning workspace state", () => {
  it("date switching exposes markers for only the selected date", () => { expect(markersForDay(day(2)).map((m) => m.itemId)).toEqual(["item-2"]) })
  it("marker identity is the same identity used by itinerary cards", () => { expect(markersForDay(day(1))[0].itemId).toBe(day(1).items[0].item_id) })
  it("fitBounds input excludes locations without coordinates", () => { expect(markersForDay(day(1, [item("a"), item("b", 1, 2)]))).toHaveLength(1) })
  it("provides one plus before the first node and one after every node", () => { expect(insertionSlots(day(1, [item("a"), item("b")]))).toEqual([null, "a", "b"]) })
  it("a failed preview leaves the official itinerary reference untouched", () => { const days = [day(1), day(2)]; expect(days).toBe(days) })
  it("applying a local patch replaces only the selected day", () => { const days = [day(1), day(2)]; const next = replaceOneDay(days, "day_2", day(2, [item("new")])); expect(next[0]).toBe(days[0]); expect(next[1].items[0].item_id).toBe("new") })
  it("switching dates returns no stale routes from the previous day", () => { const route = { segment_id:"s",from_item_id:"a",to_item_id:"b",travel_mode:"WALK",duration_minutes:1,status:"REAL_ROUTE" } as RouteSegment; expect(routesForDay({ day_1:[route] }, "day_2")).toEqual([]) })
})
