const api = require('../../utils/api')

Page({
  data: { navH: 64, loading: true, active: 'intent', tabs: [{ key: 'intent', label: '意图' }, { key: 'memory', label: '记忆' }, { key: 'tools', label: '工具' }, { key: 'quality', label: '质量' }, { key: 'changes', label: '变更' }, { key: 'developer', label: '开发者' }], insight: {} },
  onLoad(options) { this.tripId = options.tripId || wx.getStorageSync('travel-agent:active-trip-id'); this.load() },
  onNavReady(event) { this.setData({ navH: event.detail.totalHeight }) },
  goBack() { wx.navigateBack() },
  chooseTab(event) { this.setData({ active: event.currentTarget.dataset.key }) },
  async load() {
    try { this.setData({ insight: await api.getTripInsight(this.tripId) }) }
    catch (error) { wx.showToast({ title: error.message, icon: 'none' }) }
    finally { this.setData({ loading: false }) }
  }
})
