// 离线只读条：放在唯一提醒位（或用 xj-alert-bar type=offline）。离线时 chat-bar / 加地点 / 排序置灰
Component({
  properties: {
    text: { type: String, value: '离线 · 显示 10/18 14:20 的版本' },
    sub: { type: String, value: '只读模式，联网后可修改' },
    actionText: { type: String, value: '重试' }
  },
  methods: { onAction() { this.triggerEvent('retry', {}); } }
});
