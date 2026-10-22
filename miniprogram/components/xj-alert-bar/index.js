// 单一提醒位：传 alerts 数组，按优先级只显示一条，其余折叠为「N 条提醒」
// 优先级：服务降级(1) > 天气/行程风险(2) > 质量草稿(3) > info(4)
const META = {
  error: { p: 1, tone: 'error', icon: 'error-red' },
  degraded: { p: 1, tone: 'error', icon: 'warn-red' },
  offline: { p: 1, tone: 'error', icon: 'offline-red' },
  risk: { p: 2, tone: 'warn', icon: 'warn-amber' },
  quality: { p: 3, tone: 'warn', icon: 'shield-amber' },
  warn: { p: 3, tone: 'warn', icon: 'warn-amber' },
  info: { p: 4, tone: 'info', icon: 'info-blue' }
};
Component({
  properties: {
    alerts: { type: Array, value: [] }, // [{ id, type:'error'|'degraded'|'offline'|'quality'|'risk'|'info', text, actionText }]
    type: { type: String, value: '' },  // 兼容单条用法
    text: { type: String, value: '' },
    actionText: { type: String, value: '' },
    closable: { type: Boolean, value: false }
  },
  data: { list: [], top: null, rest: [], expanded: false },
  observers: {
    'alerts, type, text, actionText'(alerts, type, text, actionText) {
      let src = (alerts && alerts.length) ? alerts : (text ? [{ id: 'single', type: type || 'risk', text, actionText }] : []);
      const list = src.map((a, i) => {
        const m = META[a.type] || META.info;
        return Object.assign({ id: a.id != null ? a.id : i }, a, { tone: m.tone, icon: m.icon, p: m.p, i });
      }).sort((x, y) => x.p - y.p || x.i - y.i);
      this.setData({ list, top: list[0] || null, rest: list.slice(1), expanded: list.length > 1 ? this.data.expanded : false });
    }
  },
  methods: {
    toggle() { this.setData({ expanded: !this.data.expanded }); this.triggerEvent('toggle', { expanded: this.data.expanded }); },
    onAction(e) { const id = e.currentTarget.dataset.id; this.triggerEvent('action', { id, alert: this.data.list.find(a => a.id === id) }); },
    onClose(e) { this.triggerEvent('close', { id: e.currentTarget.dataset.id }); }
  }
});
