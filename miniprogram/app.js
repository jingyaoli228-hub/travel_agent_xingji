App({
  onLaunch() {
    const api = require('./utils/api')
    const cache = require('./utils/trip-cache')
    const userId = wx.getStorageSync('travel-agent:user-id') || `guest-${Date.now()}`
    wx.setStorageSync('travel-agent:user-id', userId)

    // 0.9.3 及更早体验版使用北京本地演示数据。切到真实云端时只清理
    // 这批演示 key，保留用户在真实后端创建的行程及分片离线缓存。
    if (!api.isLocalMode && wx.getStorageSync('travel-agent:runtime-mode') !== 'remote-v1') {
      const demoId = 'p0-beijing-demo'
      const activeTripId = wx.getStorageSync('travel-agent:active-trip-id')
      if (activeTripId === demoId) wx.removeStorageSync('travel-agent:active-trip-id')
      if (wx.getStorageSync('travel-agent:session-id') === demoId) wx.removeStorageSync('travel-agent:session-id')
      const keys = (wx.getStorageInfoSync().keys || []).filter(key =>
        key === `travel-agent:local-trip:${demoId}` ||
        key === `travel-agent:local-session:${demoId}` ||
        key.indexOf(`travel-agent:trip:${demoId}:`) === 0
      )
      keys.forEach(key => wx.removeStorageSync(key))
      wx.setStorageSync('travel-agent:runtime-mode', 'remote-v1')
    }

    const activeTripId = wx.getStorageSync('travel-agent:active-trip-id')
    const activeExists = activeTripId && wx.getStorageSync(`travel-agent:local-trip:${activeTripId}`)
    const seedTask = api.isLocalMode ? api.ensureDemo() : Promise.resolve({ tripId: '', overview: null })
    if (api.isLocalMode && !activeExists && api.demoTripId) {
      wx.setStorageSync('travel-agent:active-trip-id', api.demoTripId)
      wx.setStorageSync('travel-agent:session-id', api.demoTripId)
    }
    seedTask.then(({ tripId, overview }) => {
      if (tripId && !wx.getStorageSync('travel-agent:active-trip-id')) {
        wx.setStorageSync('travel-agent:active-trip-id', tripId)
        wx.setStorageSync('travel-agent:session-id', tripId)
      }
      if (overview) cache.saveTrip(overview)
    }).catch(() => {})
  },
  onShow() {
    const api = require('./utils/api')
    if (!api.isLocalMode) api.authenticate().catch(() => {})
  },
  globalData: {
    apiBaseUrl: require('./config').apiBaseUrl
  }
})
