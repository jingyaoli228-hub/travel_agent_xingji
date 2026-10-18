// 改动提示 + 撤销。默认停留 5 秒（UX 规则），消失后撤销入口在对话记录中
Component({
  properties: {
    bottom: { type: Number, value: 180 },   // rpx，位于 chat-bar 上方
    duration: { type: Number, value: 5000 }
  },
  data: { visible: false, leaving: false, text: '', actionText: '', icon: '' },
  lifetimes: { detached() { clearTimeout(this._t); clearTimeout(this._t2); } },
  methods: {
    // this.selectComponent('#toast').show({ text:'已删除 前门大街', actionText:'撤销', payload:{...} })
    show(opt = {}) {
      clearTimeout(this._t); clearTimeout(this._t2);
      this._payload = opt.payload;
      this.setData({ visible: true, leaving: false, text: opt.text || '', actionText: opt.actionText == null ? '撤销' : opt.actionText, icon: opt.icon || '' });
      const d = opt.duration || this.data.duration;
      if (d > 0) this._t = setTimeout(() => this.hide('timeout'), d);
    },
    hide(reason = 'manual') {
      clearTimeout(this._t);
      this.setData({ leaving: true });
      this._t2 = setTimeout(() => { this.setData({ visible: false, leaving: false }); this.triggerEvent('hide', { reason, payload: this._payload }); }, 200);
    },
    onAction() { this.triggerEvent('action', { payload: this._payload }); this.hide('action'); }
  }
});
