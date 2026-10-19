const config = require("../config")
const { apiBaseUrl, trialAccessKey } = config
const localApi = config.transport === 'local-demo' ? require('./local-api') : null

function request(path, options = {}) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${apiBaseUrl}${path}`,
      method: options.method || "GET",
      data: options.data,
      header: {
        "content-type": "application/json",
        ...(trialAccessKey ? { "X-Xingji-Trial-Key": trialAccessKey } : {}),
        ...(options.header || {})
      },
      timeout: options.timeout || 60000,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) resolve(res.data)
        else {
          const detail = res.data && res.data.detail
          const error = new Error(typeof detail === "string" ? detail : (detail && detail.message) || `请求失败 (${res.statusCode})`)
          error.statusCode = res.statusCode
          error.detail = detail
          reject(error)
        }
      },
      fail(err) { reject(new Error(err.errMsg || "网络连接失败")) }
    })
  })
}

function parseSse(payload) {
  if (payload && typeof payload === "object") return payload
  const blocks = String(payload || "").split(/\n\n+/)
  let finalEvent = null
  blocks.forEach((block) => {
    const line = block.split("\n").find((item) => item.indexOf("data: ") === 0)
    if (!line) return
    try {
      const event = JSON.parse(line.slice(6))
      if (event.type === "final") finalEvent = event
    } catch (_) {}
  })
  if (!finalEvent) throw new Error("服务未返回完整对话结果")
  return finalEvent
}

function postChat(sessionId, message, userId) {
  if (localApi) return localApi.postChat(sessionId, message, userId)
  return request("/api/chat/stream", {
    method: "POST",
    data: { session_id: sessionId, user_id: userId, message },
    timeout: 180000
  }).then(parseSse)
}

function getPlanningContext(userId) {
  if (localApi) return localApi.getPlanningContext(userId)
  return request(`/api/users/${encodeURIComponent(userId)}/planning-context`, { timeout: 15000 })
}

function getResearchStatus(sessionId) {
  if (localApi) return localApi.getResearchStatus(sessionId)
  return request(`/api/research/status?session_id=${encodeURIComponent(sessionId)}`, { timeout: 15000 })
}

function getSession(sessionId) {
  if (localApi) return localApi.getSession(sessionId)
  return request(`/api/session/${encodeURIComponent(sessionId)}`, { timeout: 30000 })
}

function getTripOverview(tripId) {
  if (localApi) return localApi.getTripOverview(tripId)
  return request(`/api/trips/${encodeURIComponent(tripId)}/overview`, { timeout: 120000 })
}

function rollbackPatch(tripId, planVersion) {
  if (localApi) return localApi.rollbackPatch(tripId, planVersion)
  return request(`/api/trips/${encodeURIComponent(tripId)}/rollback-patch`, {
    method: "POST",
    data: { plan_version: planVersion, request_id: `undo-${Date.now()}` },
    timeout: 30000
  })
}

function autocompletePlaces(query, city, latitude, longitude) {
  if (localApi) return localApi.autocompletePlaces(query, city, latitude, longitude)
  const params = [`q=${encodeURIComponent(query)}`, `city=${encodeURIComponent(city || '')}`]
  if (latitude != null) params.push(`latitude=${encodeURIComponent(latitude)}`)
  if (longitude != null) params.push(`longitude=${encodeURIComponent(longitude)}`)
  return request(`/api/places/autocomplete?${params.join('&')}`, { timeout: 30000 })
}

function previewInsert(tripId, dayId, payload) {
  if (localApi) return localApi.previewInsert(tripId, dayId, payload)
  return request(`/api/trips/${encodeURIComponent(tripId)}/days/${encodeURIComponent(dayId)}/preview-insert`, {
    method: 'POST', data: payload, timeout: 120000
  })
}

function applyPatch(tripId, payload) {
  if (localApi) return localApi.applyPatch(tripId, payload)
  return request(`/api/trips/${encodeURIComponent(tripId)}/apply-patch`, {
    method: 'POST', data: payload, timeout: 120000
  })
}

function reorderDay(tripId, dayId, payload) {
  if (localApi && localApi.reorderDay) return localApi.reorderDay(tripId, dayId, payload)
  return request(`/api/trips/${encodeURIComponent(tripId)}/days/${encodeURIComponent(dayId)}/reorder`, {
    method: 'POST', data: payload, timeout: 120000
  })
}

function setItemLock(tripId, dayId, itemId, payload) {
  if (localApi && localApi.setItemLock) return localApi.setItemLock(tripId, dayId, itemId, payload)
  return request(`/api/trips/${encodeURIComponent(tripId)}/days/${encodeURIComponent(dayId)}/items/${encodeURIComponent(itemId)}/lock`, {
    method: 'POST', data: payload, timeout: 30000
  })
}

function deleteItem(tripId, dayId, itemId, payload) {
  if (localApi && localApi.deleteItem) return localApi.deleteItem(tripId, dayId, itemId, payload)
  return request(`/api/trips/${encodeURIComponent(tripId)}/days/${encodeURIComponent(dayId)}/items/${encodeURIComponent(itemId)}/delete`, {
    method: 'POST', data: payload, timeout: 120000
  })
}

function listTrips(userId) { return localApi ? localApi.listTrips(userId) : request(`/api/trips?user_id=${encodeURIComponent(userId)}`, { timeout: 30000 }) }
function deleteTrip(tripId) { return localApi ? localApi.deleteTrip(tripId) : request(`/api/trips/${encodeURIComponent(tripId)}`, { method: 'DELETE', timeout: 30000 }) }
function copyTrip(tripId, userId) { return localApi ? localApi.copyTrip(tripId, userId) : request(`/api/trips/${encodeURIComponent(tripId)}/copy`, { method: 'POST', data: { user_id: userId }, timeout: 30000 }) }
function getTripInsight(tripId) { return localApi ? localApi.getTripInsight(tripId) : request(`/api/trips/${encodeURIComponent(tripId)}/insight`, { timeout: 30000 }) }
function parseXhs(userId, content) { return localApi ? localApi.parseXhs(userId, content) : request('/api/imports/xhs/parse', { method: 'POST', data: { user_id: userId, content }, timeout: 120000 }) }
function storeXhs(payload) { return localApi ? localApi.storeXhs(payload) : request('/api/imports/xhs/store', { method: 'POST', data: payload, timeout: 60000 }) }

function ensureDemo() {
  return localApi ? localApi.ensureDemo() : Promise.resolve({ tripId: '', overview: null })
}

module.exports = {
  postChat, getResearchStatus, getSession, getPlanningContext, getTripOverview, rollbackPatch,
  autocompletePlaces, previewInsert, applyPatch, reorderDay, setItemLock, deleteItem,
  listTrips, deleteTrip, copyTrip, getTripInsight,
  parseXhs, storeXhs, ensureDemo, isLocalMode: Boolean(localApi),
  demoTripId: localApi ? localApi.DEMO_TRIP_ID : ''
}
