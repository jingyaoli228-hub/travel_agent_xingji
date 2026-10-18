// 待定空位：「午餐 · 待定」，不留空
Component({
  properties: {
    label: { type: String, value: '午餐 · 待定' },
    time: { type: String, value: '' },
    actionText: { type: String, value: '去挑选 ›' },
    slotId: { type: null, value: null },
    interactive: { type: Boolean, value: true }
  },
  methods: { onTap() { if (this.data.interactive) this.triggerEvent('tap', { id: this.data.slotId }); } }
});
