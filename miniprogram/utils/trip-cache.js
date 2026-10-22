const PREFIX = "travel-agent:trip:"
const MAX_KEY_BYTES = 900 * 1024
const PLAY_PREFIX = "travel-agent:play-card:"
const MAX_STORAGE_BYTES = 8 * 1024 * 1024

function bytes(value) {
  return unescape(encodeURIComponent(JSON.stringify(value))).length
}

function freeSpace(requiredBytes, keepTripId) {
  const info = wx.getStorageInfoSync()
  const limitBytes = Math.min(Number(info.limitSize || 10 * 1024) * 1024, MAX_STORAGE_BYTES)
  if ((Number(info.currentSize || 0) * 1024) + requiredBytes < limitBytes) return
  const groups = {}
  ;(info.keys || []).filter(key => key.indexOf(PREFIX) === 0).forEach(key => {
    const tripId = key.slice(PREFIX.length).split(':')[0]
    if (tripId === keepTripId) return
    groups[tripId] = groups[tripId] || { keys: [], cachedAt: 0 }
    groups[tripId].keys.push(key)
    if (key.endsWith(':meta')) groups[tripId].cachedAt = Number(wx.getStorageSync(key).cached_at || 0)
  })
  Object.keys(groups).sort((a, b) => groups[a].cachedAt - groups[b].cachedAt).forEach(tripId => {
    if ((Number(wx.getStorageInfoSync().currentSize || 0) * 1024) + requiredBytes < limitBytes) return
    groups[tripId].keys.forEach(key => wx.removeStorageSync(key))
  })
  if ((Number(wx.getStorageInfoSync().currentSize || 0) * 1024) + requiredBytes >= limitBytes) {
    throw new Error('本地缓存空间不足，已保留当前行程')
  }
}

function safeSet(key, value, keepTripId) {
  const requiredBytes = bytes(value)
  if (requiredBytes > MAX_KEY_BYTES) throw new Error(`缓存项超过 900KB: ${key}`)
  const current = wx.getStorageSync(key)
  const growthBytes = Math.max(0, requiredBytes - (current == null ? 0 : bytes(current)))
  freeSpace(growthBytes, keepTripId)
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
    latest_diff: overview.latest_diff || {},
    conversation_history: (overview.conversation_history || []).slice(-80),
    changes: (overview.changes || []).slice(-30),
    day_ids: days.map(day => day.day_id || `day_${day.day_number}`),
    cached_at: Date.now()
  }, tripId)
  days.forEach((day) => {
    const dayId = day.day_id || `day_${day.day_number}`
    safeSet(`${PREFIX}${tripId}:day:${dayId}`, {
      day,
      routes: (overview.route_segments_by_day || {})[dayId] || []
    }, tripId)
  })
  const playcards = require('../data/beijing-top20-playcards')
  playcards.forEach(card => {
    const key = `${PLAY_PREFIX}${encodeURIComponent(card.name)}`
    const existing = wx.getStorageSync(key)
    if (existing && existing.card && existing.card.sourceStatus === '你的导入笔记') return
    safeSet(key, { card, cached_at: Date.now() }, tripId)
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

function loadPlayCard(name) {
  const cached = wx.getStorageSync(`${PLAY_PREFIX}${encodeURIComponent(name)}`)
  return cached && cached.card || null
}

function savePlayCard(card) {
  if (card && card.name) safeSet(`${PLAY_PREFIX}${encodeURIComponent(card.name)}`, { card, cached_at: Date.now() })
}

module.exports = { saveTrip, loadTrip, loadPlayCard, savePlayCard, MAX_KEY_BYTES }
