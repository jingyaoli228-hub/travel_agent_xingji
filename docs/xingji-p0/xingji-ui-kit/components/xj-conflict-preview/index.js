// 加点冲突预览：先预览，再决定。「仍然加入」后页面需把该节点 itinerary-card 设 conflict="原因"（标红，不静默）
Component({
  properties: {
    title: { type: String, value: '加入后会影响当天安排' },
    dayLabel: { type: String, value: 'Day 1 结束时间' },
    before: { type: String, value: '' },   // '18:30'
    after: { type: String, value: '' },    // '20:10'
    over: { type: Boolean, value: false }, // after 超出约束 → 红色
    impacts: { type: Array, value: [] },   // [{ text, level:'warn'|'error'|'info' }]
    applyText: { type: String, value: '按建议调整' },
    forceText: { type: String, value: '仍然加入' }
  },
  methods: {
    onApply() { this.triggerEvent('apply', {}); },
    onForce() { this.triggerEvent('force', {}); }
  }
});
