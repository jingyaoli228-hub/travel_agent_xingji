Component({
  properties: {
    mode: { type: String, value: 'walk' }, // walk | subway | bus | taxi | bike
    text: { type: String, value: '' },     // '地铁 5 号线 · 18 分钟'
    estimated: { type: Boolean, value: false } // 估算段：前缀 ≈、虚线更稀、带「估算」标
  },
  methods: { onTap() { this.triggerEvent('tap', { mode: this.data.mode, estimated: this.data.estimated }); } }
});
