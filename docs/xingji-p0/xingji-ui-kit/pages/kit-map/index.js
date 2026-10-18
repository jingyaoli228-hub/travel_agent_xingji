const { poiMarker, typeMarker, routeLine } = require('../../utils/map-style.js');
const pts = [
  { latitude: 39.8822, longitude: 116.4066 }, { latitude: 39.8930, longitude: 116.3990 },
  { latitude: 39.8970, longitude: 116.3980 }, { latitude: 39.9050, longitude: 116.4010 }
];
Page({
  data: {
    navH: 64, level: 'half', day: 0, score: 78, focus: false, offline: false,
    days: [{ label: 'Day 1', sub: '周六', today: true }, { label: 'Day 2', sub: '周日', warn: true }, { label: 'Day 3', sub: '周一' }],
    alerts: [{ id: 'q', type: 'quality', text: '评审 78：午餐未定、Day2 步行偏多', actionText: '看透视' }, { id: 'r', type: 'risk', text: '周日下午雷阵雨' }],
    steps: [{ title: '东门进 · 祈年殿', time: '40min' }, { title: '回音壁', time: '30min' }, { title: '圜丘坛', time: '20min' }],
    markers: [
      poiMarker(1, pts[0].latitude, pts[0].longitude, 1), typeMarker(2, pts[1].latitude, pts[1].longitude, 'restaurant-orange'),
      poiMarker(3, pts[2].latitude, pts[2].longitude, 3), poiMarker(4, pts[3].latitude, pts[3].longitude, 4),
      typeMarker(9, 39.8800, 116.4150, 'current')
    ],
    polyline: [routeLine(pts, 'current')]
  },
  onNavReady(e) { this.setData({ navH: e.detail.totalHeight }); },
  onMyTrips() { wx.showToast({ title: '→ 我的行程', icon: 'none' }); },
  openInsight() { wx.showToast({ title: '打开 Agent 透视面板', icon: 'none' }); },
  onLevel(e) { this.setData({ level: e.detail.level }); },
  onDay(e) { this.setData({ day: e.detail.index }); },
  onMarker() { this.setData({ focus: true, level: 'half' }); },
  onCard() { this.setData({ focus: true, level: 'half' }); },
  onExpand(e) { this.setData({ level: e.detail.expanded ? 'full' : 'half' }); },
  onCloseNode() { this.setData({ focus: false }); },
  onNodeAct(e) { if (e.detail.act === 'delete') { this.setData({ focus: false }); this.selectComponent('#toast').show({ text: '已删除 天坛公园' }); } },
  onSend(e) { this.selectComponent('#toast').show({ text: '已调整：下午改为前门大街慢逛' }); },
  toggleOffline() { this.setData({ offline: !this.data.offline }); }
});
