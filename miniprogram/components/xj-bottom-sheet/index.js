// 三档抽屉：peek / half / full。仅「把手 + header 插槽（放 Day Tab）」可拖，列表区只滚动（UX 手势规则）
Component({
  options: { multipleSlots: true },
  properties: {
    level: { type: String, value: 'half' },   // peek | half | full（受控，可外部改）
    peekHeight: { type: Number, value: 300 }, // rpx，露出高度
    halfRatio: { type: Number, value: 0.52 }, // 半屏占窗口高度比例
    topOffset: { type: Number, value: 0 },    // px，full 时距顶（传 nav-bar 的 totalHeight）
    headerHeight: { type: Number, value: 160 },// rpx，头部估算高度（计算滚动区）
    bottomPad: { type: Number, value: 180 },  // rpx，列表底部留白（为 chat-bar 让位）
    scrollAlways: { type: Boolean, value: false },
    scrollDisabled: { type: Boolean, value: false }
  },
  data: { y: 0, fullH: 600, bodyH: 400, dragging: false },
  lifetimes: {
    attached() {
      const win = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
      this._rpx = win.windowWidth / 750;
      this._winH = win.windowHeight;
      this.layout();
    }
  },
  observers: { 'level, topOffset, peekHeight, halfRatio'() { if (this._winH) this.layout(); } },
  methods: {
    snaps() {
      const fullH = this._winH - this.data.topOffset;
      return { fullH, full: 0, half: fullH - this._winH * this.data.halfRatio, peek: fullH - this.data.peekHeight * this._rpx };
    },
    layout() {
      const s = this.snaps();
      this.setData({ fullH: s.fullH, bodyH: s.fullH - this.data.headerHeight * this._rpx, y: s[this.data.level] != null ? s[this.data.level] : s.half });
    },
    onStart(e) { this._sy = e.touches[0].clientY; this._y0 = this.data.y; this._t0 = Date.now(); this.setData({ dragging: true }); },
    onMove(e) {
      const s = this.snaps(); let y = this._y0 + e.touches[0].clientY - this._sy;
      y = Math.max(s.full, Math.min(s.peek, y));
      this.setData({ y });
    },
    onEnd() {
      const s = this.snaps(); const y = this.data.y; const v = (y - this._y0) / Math.max(1, Date.now() - this._t0);
      const order = ['full', 'half', 'peek']; let level;
      if (Math.abs(v) > 0.6) { const cur = order.indexOf(this.data.level); level = order[Math.max(0, Math.min(2, cur + (v > 0 ? 1 : -1)))]; }
      else level = order.reduce((a, b) => Math.abs(s[b] - y) < Math.abs(s[a] - y) ? b : a);
      this.setData({ dragging: false, level, y: s[level] });
      this.triggerEvent('change', { level });
    },
    onLower() { this.triggerEvent('scrolltolower', {}); },
    setLevel(level) { this.setData({ level }); this.triggerEvent('change', { level }); }
  }
});
