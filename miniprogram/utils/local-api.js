const { buildDemoTrip, placeCatalog, dateOffset } = require('../data/p0-demo')

const DEMO_TRIP_ID = 'p0-beijing-demo'
const IDS_KEY = 'travel-agent:local-trip-ids'
const TRIP_PREFIX = 'travel-agent:local-trip:'
const SESSION_PREFIX = 'travel-agent:local-session:'
const IMPORT_PREFIX = 'travel-agent:local-import:'

function clone(value) { return JSON.parse(JSON.stringify(value)) }
function tripKey(id) { return `${TRIP_PREFIX}${id}` }
function sessionKey(id) { return `${SESSION_PREFIX}${id}` }
function delay(value, ms) { return new Promise(resolve => setTimeout(() => resolve(clone(value)), ms == null ? 180 : ms)) }

function readIds() { return wx.getStorageSync(IDS_KEY) || [] }
function writeIds(ids) { wx.setStorageSync(IDS_KEY, Array.from(new Set(ids))) }
function readTrip(id) { return wx.getStorageSync(tripKey(id)) || null }
function saveTrip(trip) {
  trip.updated_at = Date.now()
  wx.setStorageSync(tripKey(trip.trip_id), trip)
  writeIds([trip.trip_id].concat(readIds().filter(id => id !== trip.trip_id)))
  return trip
}
function readSession(id) { return wx.getStorageSync(sessionKey(id)) || null }
function saveSession(session) { wx.setStorageSync(sessionKey(session.tripId), session); return session }

function ensureDemo() {
  let trip = readTrip(DEMO_TRIP_ID)
  if (!trip) trip = saveTrip(buildDemoTrip(DEMO_TRIP_ID))
  return delay({ tripId: DEMO_TRIP_ID, overview: trip }, 20)
}

function inferRequirement(text) {
  const daysMatch = String(text).match(/(\d+)\s*天/)
  const destination = ['北京', '杭州', '成都', '上海', '西安'].find(city => String(text).includes(city)) || '北京'
  const travelers = /爸妈|父母/.test(text) ? '3 人（含长辈）' : '2 人'
  return { destination, duration_days: daysMatch ? Number(daysMatch[1]) : 3, travelers, traveler_count: /爸妈|父母/.test(text) ? 3 : 2, daily_attraction_count: 3 }
}

function selectionPayload(requirement) {
  const rows = placeCatalog.slice(0, 11).map(place => ({ name: place.name, place_id: place.place_id, type: place.type, rating: place.rating }))
  return {
    stage: 'selection',
    travel_requirement: requirement,
    candidates: { experiences: { '经典人文': rows.slice(0, 6), '公园与街区': rows.slice(6) } }
  }
}

function buildPlannedTrip(session, chosenNames) {
  const base = buildDemoTrip(session.tripId)
  const days = Math.max(1, Number(session.requirement.duration_days || 3))
  base.days = base.days.slice(0, Math.min(days, base.days.length))
  base.title = `${session.requirement.destination || '北京'} ${base.days.length} 日游`
  base.subtitle = base.days.length ? `${base.days[0].date.slice(5)} - ${base.days[base.days.length - 1].date.slice(5)}` : ''
  if (chosenNames && chosenNames.length) {
    const keep = new Set(chosenNames)
    base.days.forEach(day => {
      const filtered = day.items.filter(item => keep.has(item.name))
      if (filtered.length) day.items = filtered
    })
  }
  base.conversation_history = (session.messages || []).concat({ role: 'assistant', content: '草稿已生成；路线、停留时长和风险提示已完成首轮评审。' })
  base.quality = { score: 91, passed: true, issues: [] }
  saveTrip(base)
  session.stage = 'done'
  saveSession(session)
  return {
    response: '已生成可编辑的行程草稿。',
    data: { stage: 'done', travel_requirement: session.requirement, itinerary: { days: clone(base.days) }, review_report: clone(base.quality) }
  }
}

function postChat(sessionId, message, userId) {
  const trip = readTrip(sessionId)
  if (trip) {
    const before = clone(trip)
    trip.plan_version = Number(trip.plan_version || 1) + 1
    trip.conversation_history = (trip.conversation_history || []).concat({ role: 'user', content: message })
    let summary = '已按对话调整当天节奏'
    let reply = '已记录你的要求，并重新检查当天顺序与交通时间。'
    if (/轻松|少走|别太累/.test(message)) {
      summary = '下午节奏已放松'
      reply = '已把较远的一段改为打车，并拉开下午两个节点的间隔。'
      const day = trip.days[0]
      if (day && day.items[2]) day.items[2].time = '14:50'
      const route = (trip.route_segments_by_day.day_1 || [])[1]
      if (route) { route.travel_mode = 'DRIVE'; route.duration_minutes = 14; route.distance_meters = 2300 }
    } else if (/提前|早一点/.test(message)) {
      summary = '首个节点已提前'
      reply = '已把当天首个节点提前 30 分钟，并顺延检查后续安排。'
      if (trip.days[0] && trip.days[0].items[0]) trip.days[0].items[0].time = '08:30'
    }
    trip.conversation_history.push({ role: 'assistant', content: reply })
    trip.changes = (trip.changes || []).concat({
      plan_version: trip.plan_version,
      summary,
      changed_items: [{ action: 'UPDATE', name: summary }],
      snapshot: before
    })
    saveTrip(trip)
    return delay({ response: reply, data: { stage: 'post_plan_feedback', itinerary: { days: trip.days }, review_report: trip.quality } }, 420)
  }

  let session = readSession(sessionId)
  if (!session) {
    const requirement = inferRequirement(message)
    session = { tripId: sessionId, userId, requirement, stage: 'preferences', researchCount: 0, messages: [{ role: 'user', content: message }] }
    saveSession(session)
    return delay({ response: '我理解了，接下来确认一下偏好。', data: { stage: 'confirmation', travel_requirement: requirement } }, 350)
  }

  session.messages = (session.messages || []).concat({ role: 'user', content: message })
  if (/选择这些地点|按推荐自动选择|生成草稿/.test(message)) {
    const chosen = (message.match(/选择这些地点：([^。]+)/) || [])[1]
    return delay(buildPlannedTrip(session, chosen ? chosen.split('、') : null), 900)
  }
  if (/确认以上需求|开始规划|开始搜索/.test(message)) {
    session.stage = 'researching'; session.researchCount = 0; saveSession(session)
    return delay({ response: '正在准备目的地资料。', data: { stage: 'researching', travel_requirement: session.requirement } }, 350)
  }
  if (/自动修正/.test(message)) return delay(buildPlannedTrip(session), 700)
  session.stage = 'preferences'; saveSession(session)
  return delay({ response: '信息已补充，请确认本次偏好。', data: { stage: 'confirmation', travel_requirement: session.requirement } }, 300)
}

function getResearchStatus(sessionId) {
  const session = readSession(sessionId)
  if (!session) return delay({ status: 'idle', progress: {} }, 50)
  session.researchCount = Number(session.researchCount || 0) + 1
  const count = session.researchCount
  const progress = { amap_places: 'done', rag_guides: count >= 2 ? 'done' : 'running', route_matrix: count >= 3 ? 'done' : 'pending' }
  const done = count >= 3
  if (done) session.stage = 'selection'
  saveSession(session)
  return delay({ status: done ? 'done' : 'researching', progress }, 80)
}

function getSession(sessionId) {
  const session = readSession(sessionId)
  if (!session) return Promise.reject(new Error('会话不存在'))
  return delay({ response: '资料已准备完成，请确认装不下的候选地点。', data: selectionPayload(session.requirement) }, 120)
}

function getPlanningContext() {
  const stored = wx.getStorageSync('travel-agent:last-preferences') || {}
  return delay({ profile: { interests: stored.styles || ['人文古迹', '美食'] }, prefilled: true }, 60)
}

function publicOverview(trip) {
  const value = clone(trip)
  value.changes = (value.changes || []).map((entry, index, rows) => ({
    plan_version: entry.plan_version,
    summary: entry.summary,
    changed_items: entry.changed_items || [],
    can_undo: index === rows.length - 1
  }))
  return value
}

function getTripOverview(tripId) {
  const trip = readTrip(tripId)
  if (!trip) { const error = new Error('行程不存在'); error.statusCode = 404; return Promise.reject(error) }
  return delay(publicOverview(trip), 80)
}

function autocompletePlaces(query, city) {
  const keyword = String(query || '').trim()
  let rows = placeCatalog.filter(place => !keyword || place.name.includes(keyword) || place.type.includes(keyword))
  if (!rows.length) rows = placeCatalog.slice(0, 6).map(place => Object.assign({}, place, { name: `${keyword} · ${place.name}` }))
  return delay({ results: rows.slice(0, 10), location_bias: city || '北京' }, 180)
}

function previewInsert(tripId, dayId, payload) {
  const trip = readTrip(tripId)
  const day = trip && trip.days.find(row => row.day_id === dayId)
  const place = placeCatalog.find(row => row.place_id === payload.place_id)
  if (!trip || !day || !place) return Promise.reject(new Error('地点或行程不存在'))
  if (Number(payload.plan_version) !== Number(trip.plan_version)) {
    const error = new Error('行程版本已更新'); error.statusCode = 409; return Promise.reject(error)
  }
  if (day.items.length >= 3 && Number(payload.preferred_duration_minutes || 90) > 60 && !payload.force_insert) {
    return delay({ status: 'INSERTION_CONFLICT', reason: '按 90 分钟加入会让当天结束时间晚于 20:30', alternatives: [{ action: 'SHORTEN_DURATION', duration_minutes: 45 }] }, 220)
  }
  const patchId = `patch-${Date.now()}`
  const nextDay = clone(day)
  const added = {
    item_id: `added-${Date.now()}`, time: '16:10', activity: 'attraction', item_type: 'attraction',
    name: place.name, location: place.name, city: '北京', place_id: place.place_id,
    latitude: place.latitude, longitude: place.longitude, duration_minutes: Number(payload.preferred_duration_minutes || 60),
    rating: place.rating, reason: '你刚刚加入的地点', user_locked: Boolean(payload.user_locked),
    conflict_reason: payload.force_insert ? '强制加入：当天结束时间可能偏晚' : ''
  }
  const anchor = payload.insert_after_item_id
  const anchorIndex = anchor ? nextDay.items.findIndex(item => item.item_id === anchor) + 1 : 0
  nextDay.items.splice(Math.max(anchorIndex, 0), 0, added)
  trip.pending_patches = trip.pending_patches || {}
  trip.pending_patches[patchId] = { dayId, nextDay, addedName: place.name, snapshot: clone(day) }
  saveTrip(trip)
  return delay({ status: 'PREVIEW', patch_id: patchId, updated_day_plan: nextDay, changed_items: [{ action: 'INSERT', name: place.name }, { action: 'SHIFT', name: '后续节点' }] }, 260)
}

function applyPatch(tripId, payload) {
  const trip = readTrip(tripId)
  const patch = trip && trip.pending_patches && trip.pending_patches[payload.patch_id]
  if (!trip || !patch) return Promise.reject(new Error('预览已过期，请重新预览'))
  if (Number(payload.plan_version) !== Number(trip.plan_version)) {
    const error = new Error('行程版本已更新'); error.statusCode = 409; return Promise.reject(error)
  }
  const before = clone(trip)
  const index = trip.days.findIndex(day => day.day_id === patch.dayId)
  trip.days[index] = patch.nextDay
  trip.plan_version += 1
  delete trip.pending_patches[payload.patch_id]
  trip.changes = (trip.changes || []).concat({ plan_version: trip.plan_version, summary: `加入 ${patch.addedName} 并重算当天`, changed_items: [{ action: 'INSERT', name: patch.addedName }], snapshot: before })
  saveTrip(trip)
  return delay({ status: 'APPLIED', plan_version: trip.plan_version }, 220)
}

function rollbackPatch(tripId) {
  const trip = readTrip(tripId)
  const history = trip && trip.changes || []
  const last = history[history.length - 1]
  if (!trip || !last || !last.snapshot) return Promise.reject(new Error('没有可撤销的改动'))
  const restored = clone(last.snapshot)
  restored.plan_version = Number(trip.plan_version || 1) + 1
  restored.changes = history.slice(0, -1)
  saveTrip(restored)
  return delay({ status: 'ROLLED_BACK', plan_version: restored.plan_version, days: restored.days }, 180)
}

function reorderDay(tripId, dayId, payload) {
  const trip = readTrip(tripId)
  const day = trip && trip.days.find(row => row.day_id === dayId)
  if (!trip || !day) return Promise.reject(new Error('行程不存在'))
  const byId = Object.fromEntries(day.items.map(item => [item.item_id, item]))
  day.items = payload.ordered_item_ids.map(id => byId[id]).filter(Boolean)
  trip.plan_version += 1; saveTrip(trip)
  return delay({ status: 'SUCCESS', plan_version: trip.plan_version }, 100)
}

function previewReorder(tripId, dayId, payload) {
  const trip = readTrip(tripId)
  const day = trip && trip.days.find(row => row.day_id === dayId)
  if (!trip || !day) return Promise.reject(new Error('行程不存在'))
  if (Number(payload.plan_version) !== Number(trip.plan_version)) {
    const error = new Error('行程版本已更新'); error.statusCode = 409; return Promise.reject(error)
  }
  const existing = day.items.map(item => item.item_id)
  if (payload.ordered_item_ids.length !== existing.length || new Set(payload.ordered_item_ids).size !== existing.length || payload.ordered_item_ids.some(id => !existing.includes(id))) return Promise.reject(new Error('REORDER_ITEMS_MISMATCH'))
  const nextDay = { ...clone(day), items: payload.ordered_item_ids.map(id => clone(day.items.find(item => item.item_id === id))) }
  const conflicts = nextDay.items.some(item => item.time > '23:00') ? ['调整后当天行程可能过晚'] : []
  const patchId = `local-reorder-${Date.now()}`
  trip.pending_patches = trip.pending_patches || {}
  trip.pending_patches[patchId] = { dayId, nextDay, addedName: '', snapshot: clone(day), summary: '已手动调整当天地点顺序并重算路线' }
  saveTrip(trip)
  return delay({ status: 'PREVIEW', patch_id: patchId, updated_day_plan: nextDay, updated_route_segments: [], changed_items: [{ action: 'REORDER', from_item_ids: existing, ordered_item_ids: payload.ordered_item_ids }], plan_version: trip.plan_version, conflicts }, 100)
}

function setItemLock(tripId, dayId, itemId, payload) {
  const trip = readTrip(tripId)
  const day = trip && trip.days.find(row => row.day_id === dayId)
  const item = day && day.items.find(row => row.item_id === itemId)
  if (!item) return Promise.reject(new Error('地点不存在'))
  item.user_locked = Boolean(payload.locked); trip.plan_version += 1; saveTrip(trip)
  return delay({ status: 'SUCCESS', plan_version: trip.plan_version }, 80)
}

function deleteItem(tripId, dayId, itemId) {
  const trip = readTrip(tripId)
  const day = trip && trip.days.find(row => row.day_id === dayId)
  if (!day) return Promise.reject(new Error('行程不存在'))
  day.items = day.items.filter(row => row.item_id !== itemId); trip.plan_version += 1; saveTrip(trip)
  return delay({ status: 'SUCCESS', plan_version: trip.plan_version }, 100)
}

function listTrips() {
  const today = dateOffset(0)
  const trips = readIds().map(readTrip).filter(Boolean).map(trip => {
    const dates = (trip.days || []).map(day => day.date).filter(Boolean)
    const traveled = dates.length && dates[dates.length - 1] < today
    const ongoing = dates.length && dates[0] <= today && dates[dates.length - 1] >= today
    const status = traveled ? 'traveled' : (trip.quality && trip.quality.score >= 85 ? 'confirmed' : 'draft')
    return { trip_id: trip.trip_id, city: (trip.title || '行程').split(' ')[0], days: trip.days.length, status, ongoing, dates: dates.length ? `${dates[0].slice(5)} - ${dates[dates.length - 1].slice(5)}` : '日期待定', summary: status === 'traveled' ? '只读' : `质量 ${(trip.quality || {}).score || 0}`, updated_at: trip.updated_at || 0 }
  })
  return delay({ trips }, 80)
}

function deleteTrip(tripId) {
  wx.removeStorageSync(tripKey(tripId)); writeIds(readIds().filter(id => id !== tripId))
  return delay({ status: 'DELETED' }, 60)
}

function copyTrip(tripId) {
  const source = readTrip(tripId)
  if (!source) return Promise.reject(new Error('原行程不存在'))
  const copy = clone(source)
  copy.trip_id = `trip-${Date.now()}`
  copy.plan_version = 1
  copy.status = 'confirmed'
  copy.conversation_history = []
  copy.changes = []
  copy.pending_patches = {}
  copy.days.forEach((day, index) => { day.date = dateOffset(index + 7) })
  copy.subtitle = `${copy.days[0].date.slice(5)} - ${copy.days[copy.days.length - 1].date.slice(5)}`
  saveTrip(copy)
  return delay({ trip_id: copy.trip_id, plan_version: 1, days: copy.days.length }, 120)
}

function getTripInsight(tripId) {
  const trip = readTrip(tripId)
  if (!trip) return Promise.reject(new Error('行程不存在'))
  const realRoutes = Object.values(trip.route_segments_by_day || {}).reduce((sum, rows) => sum + rows.filter(row => row.status === 'REAL_ROUTE').length, 0)
  return delay({
    intent: { path: 'plan_trip → confirm_preferences → compose_itinerary', confidence: 0.94, source: 'P0 体验记录' },
    memory: { l0: true, l1: (trip.conversation_history || []).length, l2: 2, l3: ['偏好人文古迹与本地美食', '默认节奏适中，避免连续跨区'], source: 'P0 体验记录' },
    tools: { real_routes: realRoutes, candidate_count: 11, source: 'P0 体验记录' },
    quality: { reviewer: trip.quality.score, strict: 89, issues: trip.quality.issues || [], source: 'P0 体验记录' },
    changes: (trip.changes || []).map(row => ({ version: row.plan_version, summary: row.summary, items: row.changed_items || [] })),
    developer: { plan_version: trip.plan_version, stage: 'post_plan_feedback', node: 'final_output', source: 'P0 体验记录' }
  }, 100)
}

function parseXhs(userId, content) {
  const sourceMatch = String(content || '').match(/https?:\/\/[^\s，,]+/)
  const sourceUrl = sourceMatch ? sourceMatch[0].replace(/[。；;）)]+$/, '') : ''
  const text = String(content || '').replace(/https?:\/\/\S+/g, ' ')
  if (!text.trim()) return Promise.reject(new Error('链接打不开或需要登录，请把正文也粘贴进来'))
  const names = placeCatalog.filter(place => text.includes(place.name)).map(place => place.name)
  const fallback = ['故宫博物院', '景山公园', '什刹海'].filter(name => !names.includes(name))
  const rows = names.concat(fallback).slice(0, 6).map(name => {
    const place = placeCatalog.find(row => row.name === name)
    return { name, note: `笔记中提到 ${name}`, matched: Boolean(place), checked: Boolean(place), place_id: place && place.place_id, city: '北京', source: '用户粘贴', source_url: sourceUrl }
  })
  return delay({ import_id: `xhs-${Date.now()}`, title: (text.trim().split('\n')[0] || '北京旅行笔记').slice(0, 40), places: rows }, 420)
}

function storeXhs(payload) {
  const imports = wx.getStorageSync('travel-agent:xhs-imports') || []
  wx.setStorageSync('travel-agent:xhs-imports', [Object.assign({}, payload, { parsed: { places: payload.places, source_url: payload.places[0] && payload.places[0].source_url } }), ...imports].slice(0, 100))
  wx.setStorageSync(`${IMPORT_PREFIX}${payload.import_id}`, payload)
  return delay({ status: 'STORED', import_id: payload.import_id, places: (payload.places || []).length }, 100)
}

function listXhsImports() {
  return delay({ imports: wx.getStorageSync('travel-agent:xhs-imports') || [] }, 180)
}

module.exports = {
  DEMO_TRIP_ID,
  ensureDemo, postChat, getPlanningContext, getResearchStatus, getSession, getTripOverview,
  rollbackPatch, autocompletePlaces, previewInsert, applyPatch, reorderDay, previewReorder, setItemLock, deleteItem,
  listTrips, deleteTrip, copyTrip,
  getTripInsight, parseXhs, storeXhs, listXhsImports
}
