// 我的行程列表项。状态按日期自动判断，不让用户手动改（UX）
const TEXT = { draft: '草稿', confirmed: '已定', traveled: '已出行' };
Component({
  properties: {
    city: { type: String, value: '' },
    dates: { type: String, value: '' },     // '10/24 - 10/26'
    days: { type: Number, value: 0 },
    status: { type: String, value: 'draft' }, // draft | confirmed | ongoing | traveled
    summary: { type: String, value: '' },
    cover: { type: String, value: '' },     // CSS background，可传渐变
    tripId: { type: null, value: null }
  },
  data: { statusText: TEXT.draft },
  observers: { status(s) { this.setData({ statusText: TEXT[s] || s }); } },
  methods: {
    onTap() { this.triggerEvent('tap', { id: this.data.tripId }); },
    onLong() { this.triggerEvent('longpress', { id: this.data.tripId }); }
  }
});
