Component({
  properties: {
    days: { type: Array, value: [] },    // [{ label:'Day 1', sub:'周六', warn:false, today:false }]
    current: { type: Number, value: 0 }
  },
  methods: {
    onTap(e) {
      const index = Number(e.currentTarget.dataset.index);
      if (index === this.data.current) return;
      this.setData({ current: index });
      this.triggerEvent('change', { index });
    }
  }
});
