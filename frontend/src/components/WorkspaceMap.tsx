import { useEffect, useRef, useState } from "react"
import type { MapMarker, RouteSegment } from "../types"

type AMapInstance = any
declare global { interface Window { AMap?: any; _AMapSecurityConfig?: { securityJsCode: string }; __amapPromise?: Promise<void> } }

function loadAMap(): Promise<void> {
  if (window.AMap) return Promise.resolve()
  if (window.__amapPromise) return window.__amapPromise
  const key = import.meta.env.VITE_AMAP_JS_API_KEY as string | undefined
  const securityJsCode = import.meta.env.VITE_AMAP_JS_SECURITY_CODE as string | undefined
  if (!key) return Promise.reject(new Error("高德地图浏览器 Key 未配置"))
  if (securityJsCode) window._AMapSecurityConfig = { securityJsCode }
  window.__amapPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script")
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(key)}`
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => reject(new Error("高德地图加载失败"))
    document.head.appendChild(script)
  })
  return window.__amapPromise
}

const routeColor: Record<string, string> = { WALK: "#10b981", TRANSIT: "#6d5efc", DRIVE: "#f97316", BICYCLE: "#06b6d4", FERRY: "#0ea5e9", FLIGHT: "#64748b" }

export function WorkspaceMap({ markers, routes, selectedItemId, onSelect, version }: {
  markers: MapMarker[]; routes: RouteSegment[]; selectedItemId?: string; onSelect: (id: string) => void; version: number
}) {
  const host = useRef<HTMLDivElement>(null)
  const map = useRef<AMapInstance>(null)
  const overlays = useRef<any[]>([])
  const [warning, setWarning] = useState<string>()

  useEffect(() => {
    let cancelled = false
    loadAMap().then(() => {
      if (cancelled || !host.current || map.current) return
      map.current = new window.AMap.Map(host.current, { zoom: 11, center: [116.397428, 39.90923], viewMode: "2D" })
    }).catch((error) => setWarning(error instanceof Error ? error.message : String(error)))
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!map.current || !window.AMap) return
    map.current.remove(overlays.current)
    overlays.current = []
    const markerByItem = new Map<string, MapMarker>()
    markers.forEach((entry) => {
      markerByItem.set(entry.itemId, entry)
      const label = entry.type === "hotel" ? "H" : String(entry.sequence)
      const color = entry.type === "restaurant" ? "#f97316" : entry.type === "hotel" ? "#0f766e" : "#6d5efc"
      const content = `<button aria-label="${entry.name}" style="width:${entry.itemId === selectedItemId ? 34 : 28}px;height:${entry.itemId === selectedItemId ? 34 : 28}px;border:2px solid white;border-radius:50%;background:${color};color:white;font-weight:700;box-shadow:0 2px 8px #0004">${label}</button>`
      const marker = new window.AMap.Marker({ position: [entry.longitude, entry.latitude], title: entry.name, content, anchor: "center" })
      marker.on("click", async () => {
        onSelect(entry.itemId)
        let html = `<strong>${entry.name}</strong><br>${entry.type}`
        if (entry.placeId) {
          try {
            const response = await fetch(`/api/places/${encodeURIComponent(entry.placeId)}`)
            const details = await response.json()
            if (response.ok) html = `<strong>${details.name || entry.name}</strong><br>${details.address || ""}<br>${details.rating ? `★ ${details.rating}` : ""}`
          } catch { /* marker remains usable */ }
        }
        const info = new window.AMap.InfoWindow({ content: `<div style="padding:8px">${html}</div>`, offset: new window.AMap.Pixel(0, -18) })
        info.open(map.current, [entry.longitude, entry.latitude])
        overlays.current.push(info)
      })
      overlays.current.push(marker)
    })
    routes.forEach((segment) => {
      let path: number[][] = (segment.polyline || []).map((point) => [point.lng, point.lat])
      if (path.length < 2) {
        const from = markerByItem.get(segment.from_item_id); const to = markerByItem.get(segment.to_item_id)
        if (from && to) path = [[from.longitude, from.latitude], [to.longitude, to.latitude]]
      }
      if (path.length > 1) {
        overlays.current.push(new window.AMap.Polyline({ path, strokeColor: routeColor[segment.travel_mode] || "#6d5efc",
          strokeOpacity: segment.status === "REAL_ROUTE" ? .9 : .55,
          strokeWeight: selectedItemId && [segment.from_item_id, segment.to_item_id].includes(selectedItemId) ? 7 : 4,
          strokeStyle: segment.status === "REAL_ROUTE" ? "solid" : "dashed" }))
      }
    })
    map.current.add(overlays.current)
    if (overlays.current.length) map.current.setFitView(overlays.current, false, [56, 56, 56, 56])
    setWarning(routes.find((route) => route.status !== "REAL_ROUTE")?.warning || undefined)
  }, [markers, routes, selectedItemId, onSelect, version])

  return <div className="relative h-full min-h-[360px] overflow-hidden rounded-2xl bg-[var(--surface-2)]">
    <div ref={host} className="h-full w-full" aria-label="当日行程地图" />
    {warning && <div className="absolute right-3 bottom-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900 shadow">{warning}</div>}
  </div>
}
