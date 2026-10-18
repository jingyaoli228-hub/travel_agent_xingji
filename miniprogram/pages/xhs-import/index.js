const api = require('../../utils/api')

Page({
  data: { navH: 64, phase: 'input', content: '', parsed: null, error: '', busy: false },
  onLoad() {
    const content = wx.getStorageSync('travel-agent:xhs-draft') || ''
    wx.removeStorageSync('travel-agent:xhs-draft')
    this.setData({ content })
    if (content) this.parse()
  },
  onNavReady(event) { this.setData({ navH: event.detail.totalHeight }) },
  goBack() { wx.navigateBack() },
  onInput(event) { this.setData({ content: event.detail.value }) },
  paste() { wx.getClipboardData({ success: result => this.setData({ content: result.data || '' }) }) },
  async parse() {
    if (!this.data.content.trim() || this.data.busy) return
    this.setData({ phase: 'parsing', busy: true, error: '' })
    try {
      const parsed = await api.parseXhs(wx.getStorageSync('travel-agent:user-id') || 'owner', this.data.content)
      this.setData({ parsed, phase: 'result' })
    } catch (error) { this.setData({ phase: 'error', error: error.message || '解析失败' }) }
    finally { this.setData({ busy: false }) }
  },
  onPlaceChange(event) { this.setData({ [`parsed.places[${event.detail.index}].checked`]: event.detail.checked }) },
  fixPlace(event) {
    const index = event.detail.index
    const name = this.data.parsed.places[index].name
    wx.showModal({ title: '确认地点', editable: true, placeholderText: '补充城市或正确地点名', content: name, success: result => { if (result.confirm && result.content) this.setData({ [`parsed.places[${index}].name`]: result.content }) } })
  },
  copyOrigin() {
    const match = this.data.content.match(/https?:\/\/\S+/)
    if (match) wx.setClipboardData({ data: match[0], success: () => wx.showToast({ title: '链接已复制', icon: 'none' }) })
  },
  selectedPlaces() { return (this.data.parsed.places || []).filter(item => item.matched && item.checked !== false) },
  async storeOnly() {
    if (this.data.busy) return
    this.setData({ busy: true })
    try {
      await api.storeXhs({ user_id: wx.getStorageSync('travel-agent:user-id') || 'owner', import_id: this.data.parsed.import_id, content: this.data.content, places: this.selectedPlaces() })
      wx.showToast({ title: '已存入个人知识库', icon: 'success' })
      setTimeout(() => wx.navigateBack(), 600)
    } catch (error) { wx.showToast({ title: error.message, icon: 'none' }) }
    finally { this.setData({ busy: false }) }
  },
  async addToTrip() {
    const places = this.selectedPlaces()
    if (!places.length) return
    try {
      await api.storeXhs({ user_id: wx.getStorageSync('travel-agent:user-id') || 'owner', import_id: this.data.parsed.import_id, content: this.data.content, places })
      const tripId = wx.getStorageSync('travel-agent:active-trip-id')
      if (!tripId) { wx.showToast({ title: '已存知识库；请先创建行程', icon: 'none' }); return }
      const overview = await api.getTripOverview(tripId)
      const day = (overview.days || [])[0]
      if (!day) return
      wx.redirectTo({ url: `/pages/add-place/index?tripId=${encodeURIComponent(tripId)}&dayId=${encodeURIComponent(day.day_id || 'day_1')}&query=${encodeURIComponent(places[0].name)}` })
    } catch (error) { wx.showToast({ title: error.message, icon: 'none' }) }
  },
  retry() { this.parse() }
})
