// 自定义导航栏：页面 json 需 "navigationStyle": "custom"
// 依据 wx.getMenuButtonBoundingClientRect 对齐胶囊，右侧胶囊区域不放任何内容
Component({
  properties: {
    title: { type: String, value: '' },
    subtitle: { type: String, value: '' },
    leftText: { type: String, value: '我的行程' },
    showLeft: { type: Boolean, value: true },
    bg: { type: String, value: 'transparent' },   // 地图页透明；列表页可传 '#F7F5F0'
    placeholder: { type: Boolean, value: false }  // 是否占位（非地图页设 true）
  },
  data: { statusBarHeight: 20, navHeight: 44, capsuleSpace: 96, totalHeight: 64 },
  lifetimes: {
    attached() {
      try {
        const win = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
        const sb = win.statusBarHeight || 20;
        const m = wx.getMenuButtonBoundingClientRect();
        const navHeight = m && m.height ? (m.top - sb) * 2 + m.height : 44;
        const capsuleSpace = m && m.left ? win.windowWidth - m.left + 8 : 96;
        this.setData({ statusBarHeight: sb, navHeight, capsuleSpace, totalHeight: sb + navHeight });
        this.triggerEvent('ready', { statusBarHeight: sb, navHeight, totalHeight: sb + navHeight });
      } catch (e) { /* 使用默认值 */ }
    }
  },
  methods: { onLeft() { this.triggerEvent('left', {}); } }
});
