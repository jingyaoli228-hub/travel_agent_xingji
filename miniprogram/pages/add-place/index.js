const api = require('../../utils/api')

Page({
  data: { navH: 64, query: '', city: '', results: [], days: [], currentDay: 0, selected: null, preview: null, conflict: null, conflictImpacts: [], busy: false, planVersion: 0 },
  onLoad(options) {
    this.tripId = options.tripId || wx.getStorageSync('travel-agent:active-trip-id')
    this.dayId = options.dayId || ''
    const query = decodeURIComponent(options.query || '')
    this.setData({ query })
    this.loadTrip().then(() => { if (query) this.search() })
  },
  onNavReady(event) { this.setData({ navH: event.detail.totalHeight }) },
  goBack() { wx.navigateBack() },
  onQuery(event) { this.setData({ query: event.detail.value }) },
  async loadTrip() {
    const overview = await api.getTripOverview(this.tripId)
    const days = (overview.days || []).map((day, index) => ({ label: `Day ${day.day_number || index + 1}`, sub: day.date ? day.date.slice(5) : '', dayId: day.day_id || `day_${index + 1}`, raw: day }))
    const currentDay = Math.max(0, days.findIndex(day => day.dayId === this.dayId))
    this.setData({ days, currentDay, city: (days[currentDay] && days[currentDay].raw.city) || '', planVersion: overview.plan_version || 1 })
  },
  async search() {
    if (!this.data.query.trim() || this.data.busy) return
    this.setData({ busy: true, selected: null, preview: null, conflict: null })
    try { const result = await api.autocompletePlaces(this.data.query.trim(), this.data.city); this.setData({ results: result.results || [] }) }
    catch (error) { wx.showToast({ title: error.message, icon: 'none' }) }
    finally { this.setData({ busy: false }) }
  },
  choosePlace(event) { this.setData({ selected: this.data.results[Number(event.currentTarget.dataset.index)], preview: null, conflict: null }) },
  chooseDay(event) { this.setData({ currentDay: event.detail.index, preview: null, conflict: null }) },
  async preview(forceInsert = false, duration = 90) {
    if (!this.data.selected || this.data.busy) return
    const day = this.data.days[this.data.currentDay]
    this.setData({ busy: true })
    try {
      const result = await api.previewInsert(this.tripId, day.dayId, {
        place_id: this.data.selected.place_id, plan_version: this.data.planVersion,
        request_id: `preview-${Date.now()}`, preferred_duration_minutes: duration,
        user_locked: true, force_insert: forceInsert
      })
      if (result.status === 'INSERTION_CONFLICT') this.setData({ conflict: result, conflictImpacts: [{ text: result.reason, level: 'error' }], preview: null })
      else this.setData({ preview: result, conflict: null })
    } catch (error) { await this.handleError(error) }
    finally { this.setData({ busy: false }) }
  },
  previewSelected() { this.preview(false, 90) },
  applySuggested() {
    const alternative = (this.data.conflict.alternatives || []).find(item => item.action === 'SHORTEN_DURATION')
    this.preview(false, (alternative && alternative.duration_minutes) || 45)
  },
  forceAdd() { this.preview(true, 45) },
  async apply() {
    if (!this.data.preview || this.data.busy) return
    this.setData({ busy: true })
    try {
      await api.applyPatch(this.tripId, { patch_id: this.data.preview.patch_id, plan_version: this.data.planVersion, request_id: `apply-${Date.now()}` })
      wx.showToast({ title: '已加入并重算当天', icon: 'success' })
      setTimeout(() => wx.navigateBack(), 600)
    } catch (error) { await this.handleError(error) }
    finally { this.setData({ busy: false }) }
  },
  async handleError(error) {
    if (error.statusCode === 409) {
      await this.loadTrip(); this.setData({ preview: null, conflict: null })
      wx.showToast({ title: '行程已更新，已刷新到最新版本', icon: 'none' })
    } else wx.showToast({ title: error.message || '操作失败', icon: 'none' })
  }
})
