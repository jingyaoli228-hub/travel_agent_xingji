Component({
  options: { multipleSlots: true },
  properties: {
    time: { type: String, value: '' },      // '09:00'
    duration: { type: String, value: '' },  // '2.5h'
    name: { type: String, value: '' },
    meta: { type: String, value: '' },
    locked: { type: Boolean, value: false },
    rating: { type: null, value: '' },      // 4.7，空则不显示
    active: { type: Boolean, value: false },// 与地图当前选中点联动
    dimmed: { type: Boolean, value: false },
    waitlist: { type: Boolean, value: false }, // 候补：超出容量自动放入，虚线 + 「候补」
    conflict: { type: String, value: '' },     // 「仍然加入」后的冲突原因，非空则红框并显示
    itemId: { type: null, value: null }
  },
  methods: {
    onTap() { this.triggerEvent('tap', { id: this.data.itemId }); },
    onLongPress() { this.triggerEvent('longpress', { id: this.data.itemId }); }
  }
});
