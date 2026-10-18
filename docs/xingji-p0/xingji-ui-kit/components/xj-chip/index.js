Component({
  properties: {
    label: { type: String, value: '' },
    status: { type: String, value: 'default' }, // default | selected | must | exclude
    size: { type: String, value: 'md' },        // md | sm
    closable: { type: Boolean, value: false },
    value: { type: null, value: null }
  },
  methods: {
    onTap() { this.triggerEvent('tap', { value: this.data.value, status: this.data.status }); },
    onClose() { this.triggerEvent('close', { value: this.data.value }); }
  }
});
