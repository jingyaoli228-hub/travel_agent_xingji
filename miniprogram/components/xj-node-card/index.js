// 半屏合并节点卡：点地图 marker / 列表卡片时在抽屉 half 档显示；「展开玩法」→ 页面把抽屉切到 full，并传 expanded
Component({
  options: { multipleSlots: true },
  properties: {
    index: { type: null, value: 1 },
    name: { type: String, value: '' },
    time: { type: String, value: '' },
    duration: { type: String, value: '' },
    meta: { type: String, value: '' },
    rating: { type: null, value: '' },
    locked: { type: Boolean, value: false },
    tip: { type: String, value: '' },          // 一句避坑
    expanded: { type: Boolean, value: false }, // 玩法卡（全屏）
    playDuration: { type: String, value: '' },
    steps: { type: Array, value: [] },         // [{ title, desc, time, branch }]
    itemId: { type: null, value: null }
  },
  methods: {
    onAct(e) { this.triggerEvent('action', { act: e.currentTarget.dataset.act, id: this.data.itemId }); },
    onExpand() { this.triggerEvent('expand', { expanded: !this.data.expanded, id: this.data.itemId }); },
    onClose() { this.triggerEvent('close', { id: this.data.itemId }); }
  }
});
