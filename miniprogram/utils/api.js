const { apiBaseUrl } = require("../config")

function request(path, options = {}) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${apiBaseUrl}${path}`,
      method: options.method || "GET",
      data: options.data,
      header: { "content-type": "application/json", ...(options.header || {}) },
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
  return request("/api/chat/stream", {
    method: "POST",
    data: { session_id: sessionId, user_id: userId, message },
    timeout: 60000
  }).then(parseSse)
}

function getResearchStatus(sessionId) {
  return request(`/api/research/status?session_id=${encodeURIComponent(sessionId)}`, { timeout: 15000 })
}

function getSession(sessionId) {
  return request(`/api/session/${encodeURIComponent(sessionId)}`, { timeout: 30000 })
}

function getTripOverview(tripId) {
  return request(`/api/trips/${encodeURIComponent(tripId)}/overview`, { timeout: 120000 })
}

function rollbackPatch(tripId, planVersion) {
  return request(`/api/trips/${encodeURIComponent(tripId)}/rollback-patch`, {
    method: "POST",
    data: { plan_version: planVersion, request_id: `undo-${Date.now()}` },
    timeout: 30000
  })
}

module.exports = { postChat, getResearchStatus, getSession, getTripOverview, rollbackPatch }
