const api = require('../../utils/api')

Page({
  data: { navH: 64, loading: true, trips: [] },
  onLoad() { this.loadTrips() },
  onShow() { if (this._loaded) this.loadTrips() },
  onNavReady(event) { this.setData({ navH: event.detail.totalHeight }) },
  goBack() { wx.navigateBack() },
  newTrip() { wx.navigateTo({ url: '/pages/planning/index' }) },
  importXhs() { wx.navigateTo({ url: '/pages/xhs-import/index' }) },
  async loadTrips() {
    this.setData({ loading: true })
    try {
      const result = await api.listTrips(wx.getStorageSync('travel-agent:user-id') || 'owner')
      const order = { confirmed: 0, draft: 1, traveled: 2 }
      const trips = (result.trips || []).sort((a, b) => (b.ongoing - a.ongoing) || order[a.status] - order[b.status])
      this.setData({ trips })
      this._loaded = true
    } catch (error) { wx.showToast({ title: error.message, icon: 'none' }) }
    finally { this.setData({ loading: false }) }
  },
  openTrip(event) {
    const id = event.detail.id
    wx.setStorageSync('travel-agent:active-trip-id', id)
    wx.setStorageSync('travel-agent:session-id', id)
    wx.reLaunch({ url: '/pages/itinerary/index' })
  },
  confirmDelete(event) {
    const id = event.detail.id
    const trip = this.data.trips.find(item => item.trip_id === id)
    wx.showModal({
      title: `删除「${trip ? trip.city : '这趟行程'}」？`,
      content: '行程、玩法卡和本行程对话记录会一起删除，无法恢复。',
      confirmText: '删除',
      success: async result => {
        if (!result.confirm) return
        try {
          await api.deleteTrip(id)
          if (wx.getStorageSync('travel-agent:active-trip-id') === id) wx.removeStorageSync('travel-agent:active-trip-id')
          await this.loadTrips()
        } catch (error) { wx.showToast({ title: error.message, icon: 'none' }) }
      }
    })
  }
})
