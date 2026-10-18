const PREFIX = "travel-agent:trip:"
const MAX_KEY_BYTES = 900 * 1024

function bytes(value) {
  return unescape(encodeURIComponent(JSON.stringify(value))).length
}

function safeSet(key, value) {
  if (bytes(value) > MAX_KEY_BYTES) throw new Error(`缓存项超过 900KB: ${key}`)
  wx.setStorageSync(key, value)
}

function saveTrip(overview) {
  const tripId = overview.trip_id
  const days = overview.days || []
  safeSet(`${PREFIX}${tripId}:meta`, {
    trip_id: tripId,
    title: overview.title,
    subtitle: overview.subtitle,
    status: overview.status,
    plan_version: overview.plan_version,
    quality: overview.quality,
    alerts: overview.alerts || [],
    conversation_history: (overview.conversation_history || []).slice(-80),
    changes: (overview.changes || []).slice(-30),
    day_ids: days.map(day => day.day_id || `day_${day.day_number}`),
    cached_at: Date.now()
  })
  days.forEach((day) => {
    const dayId = day.day_id || `day_${day.day_number}`
    safeSet(`${PREFIX}${tripId}:day:${dayId}`, {
      day,
      routes: (overview.route_segments_by_day || {})[dayId] || []
    })
  })
}

function loadTrip(tripId) {
  const meta = wx.getStorageSync(`${PREFIX}${tripId}:meta`)
  if (!meta || !meta.day_ids) return null
  const days = []
  const routeSegments = {}
  meta.day_ids.forEach((dayId) => {
    const cached = wx.getStorageSync(`${PREFIX}${tripId}:day:${dayId}`)
    if (!cached || !cached.day) return
    days.push(cached.day)
    routeSegments[dayId] = cached.routes || []
  })
  if (!days.length) return null
  return Object.assign({}, meta, { days, route_segments_by_day: routeSegments })
}

module.exports = { saveTrip, loadTrip, MAX_KEY_BYTES }
