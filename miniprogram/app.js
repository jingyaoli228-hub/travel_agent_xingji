App({
  onLaunch() {
    const api = require('./utils/api')
    const cache = require('./utils/trip-cache')
    const userId = wx.getStorageSync('travel-agent:user-id') || `guest-${Date.now()}`
    wx.setStorageSync('travel-agent:user-id', userId)
    const activeTripId = wx.getStorageSync('travel-agent:active-trip-id')
    const activeExists = activeTripId && wx.getStorageSync(`travel-agent:local-trip:${activeTripId}`)
    const seedTask = api.ensureDemo()
    if (api.isLocalMode && !activeExists && api.demoTripId) {
      wx.setStorageSync('travel-agent:active-trip-id', api.demoTripId)
      wx.setStorageSync('travel-agent:session-id', api.demoTripId)
    }
    seedTask.then(({ tripId, overview }) => {
      if (!wx.getStorageSync('travel-agent:active-trip-id')) {
        wx.setStorageSync('travel-agent:active-trip-id', tripId)
        wx.setStorageSync('travel-agent:session-id', tripId)
      }
      if (overview) cache.saveTrip(overview)
    }).catch(() => {})
  },
  globalData: {
    apiBaseUrl: ""
  }
})
