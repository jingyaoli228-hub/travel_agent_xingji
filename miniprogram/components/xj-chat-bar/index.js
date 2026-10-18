Component({
  properties: {
    placeholder: { type: String, value: '告诉行迹：下午想轻松点…' },
    showMic: { type: Boolean, value: true },
    sending: { type: Boolean, value: false },
    disabled: { type: Boolean, value: false },
    fixed: { type: Boolean, value: false },   // 固定在底部
    bottom: { type: Number, value: 44 },      // fixed 时距底 rpx（有 tabBar 时传 160）
    clearOnSend: { type: Boolean, value: true }
  },
  data: { value: '', recording: false },
  methods: {
    onInput(e) { this.setData({ value: e.detail.value }); this.triggerEvent('input', { value: e.detail.value }); },
    onSend() {
      const value = (this.data.value || '').trim();
      if (!value || this.data.sending) return;
      this.triggerEvent('send', { value });
      if (this.data.clearOnSend) this.setData({ value: '' });
    },
    onFocus(e) { this.triggerEvent('focus', e.detail); },
    onBlur(e) { this.triggerEvent('blur', e.detail); },
    onMicStart() { this.setData({ recording: true }); this.triggerEvent('micstart', {}); },
    onMicEnd() { this.setData({ recording: false }); this.triggerEvent('micend', {}); },
    setValue(v) { this.setData({ value: v || '' }); }
  }
});
