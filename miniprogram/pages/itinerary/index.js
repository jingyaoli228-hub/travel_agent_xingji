const api = require('../../utils/api')
const cache = require('../../utils/trip-cache')
const { COLOR, poiMarker, typeMarker, routeLineByMode } = require('../../utils/map-style')
const playcards = require('../../data/beijing-top20-playcards')

const MODE = {
  WALK: { component: 'walk', label: '步行' },
  TRANSIT: { component: 'subway', label: '公共交通' },
  DRIVE: { component: 'taxi', label: '打车' },
  BICYCLE: { component: 'bike', label: '骑行' },
  FERRY: { component: 'bus', label: '轮渡' },
  FLIGHT: { component: 'bus', label: '飞机' }
}

function tripIdFromStorage() {
  return wx.getStorageSync('travel-agent:active-trip-id') || wx.getStorageSync('travel-agent:session-id') || ''
}

function localDate() {
  const now = new Date()
  const pad = value => String(value).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

function durationLabel(minutes) {
  const value = Number(minutes || 0)
  if (!value) return ''
  if (value < 60) return `${value}min`
  const hours = Math.floor(value / 60)
  const rest = value % 60
  return rest ? `${hours}h${rest}min` : `${hours}h`
}

function cleanName(item) {
  return (item.name || item.location || '未命名地点').replace(/\s*\([^)]*\)\s*$/, '')
}

function isPendingMeal(item) {
  return ['lunch', 'dinner'].includes(item.activity) &&
    (!item.place_id || /当地特色餐厅|待定/.test(cleanName(item)))
}

Page({
  data: {
    tripId: '', navH: 64, loading: true, hasTrip: false, sending: false, offlineNoCache: false,
    title: '行迹', subtitle: '', planVersion: 0, level: 'peek',
    offline: false, readOnly: false, cachedAt: '',
    score: 0, qualityStatus: 'draft', qualityIssues: [], alerts: [],
    days: [], currentDay: 0, dayEntries: [], daySummary: '',
    markers: [], polyline: [], latitude: 39.9042, longitude: 116.4074,
    focusItem: null, conversationOpen: false, qualityOpen: false,
    messages: [], changes: [], emptyPrompts: [
      '北京 3 天，第一次去，想看经典景点',
      '周末去杭州，节奏轻松一点',
      '带父母去成都 4 天，少走路'
    ]
  },

  onLoad() {
    const tripId = tripIdFromStorage()
    this.setData({ tripId })
    this._networkHandler = status => this.onNetworkChange(status.isConnected)
    wx.onNetworkStatusChange(this._networkHandler)
    wx.getNetworkType({
      success: result => {
        const offline = result.networkType === 'none'
        this.setData({ offline, readOnly: offline })
        this.loadOverview()
      },
      fail: () => this.loadOverview()
    })
  },

  onUnload() {
    if (this._networkHandler && wx.offNetworkStatusChange) wx.offNetworkStatusChange(this._networkHandler)
  },

  onNavReady(event) { this.setData({ navH: event.detail.totalHeight }) },
  onMyTrips() { wx.navigateTo({ url: '/pages/trips/index' }) },

  onShow() {
    if (this.data.tripId && this.data.hasTrip) this.loadOverview({ silent: true })
  },

  async loadOverview(options = {}) {
    const tripId = this.data.tripId
    if (!tripId) {
      this.setData({ loading: false, hasTrip: false })
      return
    }
    if (this.data.offline) {
      const cached = cache.loadTrip(tripId)
      if (cached) this.applyOverview(cached, true)
      else this.setData({ loading: false, hasTrip: false, readOnly: true, offlineNoCache: true })
      return
    }
    if (!options.silent) this.setData({ loading: true })
    try {
      const overview = await api.getTripOverview(tripId)
      cache.saveTrip(overview)
      this.applyOverview(overview, false)
    } catch (error) {
      if (error.statusCode === 404) {
        this.setData({ loading: false, hasTrip: false, offlineNoCache: this.data.offline })
        return
      }
      const cached = cache.loadTrip(tripId)
      if (cached) {
        cached.alerts = [{ id: 'api-error', type: 'error', text: '云端暂不可用，正在显示本地版本', actionText: '重试' }].concat(cached.alerts || [])
        this.setData({ readOnly: true })
        this.applyOverview(cached, true)
      } else {
        this.setData({ loading: false, hasTrip: false })
        wx.showToast({ title: error.message || '行程加载失败', icon: 'none' })
      }
    }
  },

  applyOverview(overview, fromCache) {
    const today = localDate()
    const rawDays = overview.days || []
    const days = rawDays.map((day, index) => ({
      label: `Day ${day.day_number || index + 1}`,
      sub: day.date ? day.date.slice(5).replace('-', '/') : '',
      today: day.date === today,
      warn: false,
      dayId: day.day_id || `day_${day.day_number || index + 1}`,
      raw: day
    }))
    const todayIndex = days.findIndex(day => day.today)
    const currentDay = todayIndex >= 0 ? todayIndex : Math.min(this.data.currentDay, Math.max(days.length - 1, 0))
    const quality = overview.quality || {}
    this._overview = overview
    this.setData({
      loading: false,
      hasTrip: rawDays.length > 0,
      title: overview.title || '行迹',
      subtitle: overview.subtitle || '',
      planVersion: overview.plan_version || 0,
      tripStatus: overview.status || 'draft',
      score: Number(quality.score || 0),
      qualityStatus: quality.passed ? 'pass' : (Number(quality.score || 0) > 0 ? 'draft' : 'fail'),
      qualityIssues: quality.issues || [],
      alerts: overview.alerts || [],
      days,
      currentDay,
      messages: overview.conversation_history || [],
      changes: overview.changes || [],
      cachedAt: fromCache && overview.cached_at ? this.formatCacheTime(overview.cached_at) : '',
      readOnly: this.data.offline || fromCache || overview.status === 'traveled',
      offlineNoCache: false
    }, () => this.renderDay(currentDay))
  },

  formatCacheTime(timestamp) {
    const date = new Date(timestamp)
    const pad = value => String(value).padStart(2, '0')
    return `${pad(date.getMonth() + 1)}/${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
  },

  renderDay(index) {
    const descriptor = this.data.days[index]
    if (!descriptor || !this._overview) return
    const day = descriptor.raw
    const routes = (this._overview.route_segments_by_day || {})[descriptor.dayId] || []
    const routeByFrom = {}
    routes.forEach(route => { routeByFrom[route.from_item_id] = route })
    const items = day.items || []
    const entries = items.map((item, itemIndex) => {
      const route = routeByFrom[item.item_id] || routes[itemIndex]
      const mode = MODE[(route && route.travel_mode) || 'TRANSIT'] || MODE.TRANSIT
      return {
        node: Object.assign({}, item, {
          displayName: cleanName(item),
          durationLabel: durationLabel(item.duration_minutes),
          pendingMeal: isPendingMeal(item),
          meta: item.reason || item.location || '',
          index: itemIndex + 1,
          conflictReason: item.conflict_reason || ''
        }),
        transit: route ? {
          mode: mode.component,
          text: `${mode.label}${route.duration_minutes ? ` ${Math.round(route.duration_minutes)} 分钟` : ''}`,
          estimated: route.status !== 'REAL_ROUTE'
        } : null
      }
    })

    const markers = []
    const markerToItem = {}
    const pointsByItem = {}
    items.forEach((item, itemIndex) => {
      if (item.latitude == null || item.longitude == null) return
      const markerId = markers.length + 1
      markerToItem[markerId] = item.item_id
      pointsByItem[item.item_id] = { latitude: Number(item.latitude), longitude: Number(item.longitude) }
      const type = item.item_type || item.activity
      if (type === 'hotel' || item.activity === 'return_to_hotel') {
        markers.push(typeMarker(markerId, Number(item.latitude), Number(item.longitude), 'hotel'))
      } else if (type === 'restaurant' || ['lunch', 'dinner'].includes(item.activity)) {
        markers.push(typeMarker(markerId, Number(item.latitude), Number(item.longitude), 'restaurant-orange'))
      } else {
        markers.push(poiMarker(markerId, Number(item.latitude), Number(item.longitude), itemIndex + 1))
      }
    })
    const polyline = []
    routes.forEach(route => {
      let points = (route.polyline || []).map(point => ({ latitude: Number(point.lat), longitude: Number(point.lng) }))
      if (points.length < 2 && pointsByItem[route.from_item_id] && pointsByItem[route.to_item_id]) {
        points = [pointsByItem[route.from_item_id], pointsByItem[route.to_item_id]]
      }
      if (points.length >= 2) polyline.push(routeLineByMode(points, route.travel_mode, route.status))
    })
    const mapPoints = markers.map(marker => ({ latitude: marker.latitude, longitude: marker.longitude }))
    const center = mapPoints.length ? mapPoints.reduce((sum, point) => ({
      latitude: sum.latitude + point.latitude / mapPoints.length,
      longitude: sum.longitude + point.longitude / mapPoints.length
    }), { latitude: 0, longitude: 0 }) : { latitude: this.data.latitude, longitude: this.data.longitude }
    const walking = routes.filter(route => route.travel_mode === 'WALK').reduce((sum, route) => sum + Number(route.distance_meters || 0), 0)
    const transportMinutes = routes.reduce((sum, route) => sum + Number(route.duration_minutes || 0), 0)
    const summary = `${items.length} 站 · 交通约 ${Math.round(transportMinutes)} 分钟${walking ? ` · 步行 ${(walking / 1000).toFixed(1)}km` : ''}`
    this._markerToItem = markerToItem
    this._offlineGeometry = { markers, polyline }
    this.setData({
      currentDay: index, dayEntries: entries, daySummary: summary,
      markers, polyline, latitude: center.latitude, longitude: center.longitude,
      focusItem: null, conversationOpen: false, qualityOpen: false
    }, () => { if (this.data.offline || this.data.readOnly) setTimeout(() => this.drawOfflineRoute(), 30) })
  },

  onDay(event) { this.renderDay(event.detail.index) },
  onLevel(event) { this.setData({ level: event.detail.level }) },
  onMarker(event) { this.focusById(this._markerToItem && this._markerToItem[event.detail.markerId]) },
  onCard(event) { this.focusById(event.detail.id) },

  focusById(itemId) {
    if (!itemId) return
    const entry = this.data.dayEntries.find(row => row.node.item_id === itemId)
    if (!entry) return
    const node = entry.node
    const play = playcards.find(card => node.displayName.indexOf(card.name) >= 0 || card.name.indexOf(node.displayName) >= 0)
    this.setData({
      focusItem: Object.assign({}, node, {
        play: play || null,
        steps: play ? play.route : [{ title: node.displayName, desc: node.reason || '', time: node.durationLabel }]
      }),
      conversationOpen: false, qualityOpen: false, level: 'half'
    })
  },

  onCloseNode() { this.setData({ focusItem: null }) },
  onExpandNode(event) { this.setData({ level: event.detail.expanded ? 'full' : 'half' }) },
  onNodeAction(event) {
    if (event.detail.act === 'lock') wx.showToast({ title: '已记录锁定意图，可通过对话修改', icon: 'none' })
    else wx.showToast({ title: '请在对话栏描述这次修改', icon: 'none' })
  },

  openAddPlace(event) {
    if (this.data.readOnly) return
    const day = this.data.days[this.data.currentDay]
    const query = event && event.detail && event.detail.name ? `&query=${encodeURIComponent(event.detail.name)}` : ''
    wx.navigateTo({ url: `/pages/add-place/index?tripId=${encodeURIComponent(this.data.tripId)}&dayId=${encodeURIComponent(day.dayId)}${query}` })
  },

  expandPlay() {
    if (!this.data.focusItem || !this.data.focusItem.play) return
    this.setData({ level: 'full' })
    this.selectComponent('#toast').show({ text: '已展开玩法子节点，当天总时长不变' })
  },

  copyPlaySource(event) {
    const url = event.currentTarget.dataset.url
    if (!url) return
    wx.setClipboardData({ data: url, success: () => wx.showToast({ title: '已复制，到小红书粘贴打开', icon: 'none' }) })
  },

  openInsight() {
    wx.navigateTo({ url: `/pages/agent-insight/index?tripId=${encodeURIComponent(this.data.tripId)}` })
  },

  async copyAsNewTrip() {
    try {
      const result = await api.copyTrip(this.data.tripId, wx.getStorageSync('travel-agent:user-id') || 'owner')
      wx.setStorageSync('travel-agent:active-trip-id', result.trip_id)
      wx.setStorageSync('travel-agent:session-id', result.trip_id)
      this.setData({ tripId: result.trip_id, readOnly: false })
      await this.loadOverview()
      wx.showToast({ title: '已复制为新行程', icon: 'success' })
    } catch (error) { wx.showToast({ title: error.message, icon: 'none' }) }
  },

  onChatFocus() {
    this.setData({ conversationOpen: true, qualityOpen: false, focusItem: null, level: 'full' })
  },

  openConversation() { this.onChatFocus() },

  async onSend(event) {
    const value = event.detail.value
    if (!value || this.data.readOnly || this.data.sending) return
    if (/xhslink|xiaohongshu|小红书/.test(value) || value.length > 180) {
      wx.setStorageSync('travel-agent:xhs-draft', value)
      wx.navigateTo({ url: '/pages/xhs-import/index' })
      return
    }
    const messages = this.data.messages.concat({ role: 'user', content: value })
    this.setData({ messages, conversationOpen: true, level: 'full', sending: true })
    try {
      const userId = wx.getStorageSync('travel-agent:user-id') || this.data.tripId
      const result = await api.postChat(this.data.tripId, value, userId)
      this.setData({ messages: this.data.messages.concat({ role: 'assistant', content: result.response || '已收到。' }) })
      await this.loadOverview({ silent: true })
      this.selectComponent('#toast').show({ text: '已根据对话更新行程', payload: { undo: true } })
    } catch (error) {
      this.setData({ messages: this.data.messages.concat({ role: 'assistant', content: `修改失败：${error.message}` }) })
    } finally {
      this.setData({ sending: false })
    }
  },

  async undoLatestChange() {
    if (this.data.readOnly || !this.data.changes.some(change => change.can_undo)) return
    try {
      await api.rollbackPatch(this.data.tripId, this.data.planVersion)
      await this.loadOverview({ silent: true })
      this.selectComponent('#toast').show({ text: '已撤销上一次改动', actionText: '' })
    } catch (error) {
      wx.showToast({ title: error.message || '撤销失败', icon: 'none' })
    }
  },

  onToastAction(event) { if (event.detail.payload && event.detail.payload.undo) this.undoLatestChange() },
  onViewChange(event) {
    const change = this.data.changes[event.currentTarget.dataset.index]
    wx.showToast({ title: (change && change.summary) || '行程改动', icon: 'none' })
  },

  onAlertAction(event) {
    const id = event.detail.id
    if (id === 'route-degraded' || id === 'api-error') this.loadOverview()
    else if (id === 'quality') this.openInsight()
  },

  onNetworkChange(isConnected) {
    const offline = !isConnected
    this.setData({ offline, readOnly: offline })
    if (offline) {
      const cached = cache.loadTrip(this.data.tripId)
      if (cached) this.applyOverview(cached, true)
      else this.setData({ loading: false, hasTrip: false, offlineNoCache: true })
    } else {
      this.setData({ offlineNoCache: false })
      this.loadOverview()
    }
  },

  retryOnline() {
    wx.getNetworkType({ success: result => this.onNetworkChange(result.networkType !== 'none') })
  },

  drawOfflineRoute() {
    if (!this._offlineGeometry || !this.data.hasTrip) return
    const info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync()
    const width = info.windowWidth
    const height = info.windowHeight
    const ctx = wx.createCanvasContext('offlineRouteCanvas', this)
    ctx.setFillStyle(COLOR.mapBg); ctx.fillRect(0, 0, width, height)
    ctx.setStrokeStyle(COLOR.grid); ctx.setLineWidth(1)
    for (let x = 0; x < width; x += 40) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke() }
    for (let y = 0; y < height; y += 40) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke() }
    const all = []
    this._offlineGeometry.polyline.forEach(line => (line.points || []).forEach(point => all.push(point)))
    this._offlineGeometry.markers.forEach(marker => all.push(marker))
    if (!all.length) { ctx.draw(); return }
    const lats = all.map(point => Number(point.latitude)); const lngs = all.map(point => Number(point.longitude))
    const minLat = Math.min(...lats); const maxLat = Math.max(...lats); const minLng = Math.min(...lngs); const maxLng = Math.max(...lngs)
    const project = point => ({
      x: 32 + (Number(point.longitude) - minLng) / Math.max(maxLng - minLng, 0.0001) * (width - 64),
      y: 120 + (maxLat - Number(point.latitude)) / Math.max(maxLat - minLat, 0.0001) * Math.max(height * 0.42, 180)
    })
    this._offlineGeometry.polyline.forEach(line => {
      const points = line.points || []; if (points.length < 2) return
      ctx.beginPath(); const first = project(points[0]); ctx.moveTo(first.x, first.y)
      points.slice(1).forEach(point => { const next = project(point); ctx.lineTo(next.x, next.y) })
      ctx.setStrokeStyle(String(line.color || COLOR.primary).slice(0, 7)); ctx.setLineWidth(line.width || 4); ctx.stroke()
    })
    this._offlineGeometry.markers.forEach((marker, index) => {
      const point = project(marker); ctx.beginPath(); ctx.arc(point.x, point.y, 10, 0, Math.PI * 2)
      ctx.setFillStyle(COLOR.primary); ctx.fill(); ctx.setFillStyle(COLOR.white); ctx.setFontSize(11)
      ctx.fillText(String(index + 1), point.x - 3, point.y + 4)
    })
    ctx.draw()
  },

  onEmptyPrompt(event) {
    wx.setStorageSync('travel-agent:draft-prompt', event.detail.text)
    wx.navigateTo({ url: '/pages/planning/index' })
  },

  startPlanning() {
    wx.navigateTo({ url: '/pages/planning/index' })
  }
})
