Component({
  options: { multipleSlots: true },
  properties: {
    type: { type: String, value: 'primary' }, // primary | dark | secondary | text
    size: { type: String, value: 'md' },      // md | sm
    block: { type: Boolean, value: false },
    loading: { type: Boolean, value: false },
    disabled: { type: Boolean, value: false },
    icon: { type: String, value: '' },        // icons.wxss 名，如 'spark-white'
    openType: { type: String, value: '' }
  },
  methods: {
    onTap() {
      if (this.data.disabled || this.data.loading) return;
      this.triggerEvent('tap', {});
    }
  }
});
