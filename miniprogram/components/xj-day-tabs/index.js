Component({
  properties: {
    days: { type: Array, value: [] },    // [{ label:'Day 1', sub:'周六', warn:false, today:false }]
    current: { type: Number, value: 0 }
  },
  methods: {
    onTap(e) {
      const index = Number(e.currentTarget.dataset.index);
      if (!Number.isFinite(index)) return;
      // Controlled component: the page owns `current`. Mutating a property
      // internally raced the parent update on real devices and left Day 2/3
      // visually selected but still rendering Day 1.
      this.triggerEvent('change', { index }, { bubbles: true, composed: true });
    }
  }
});
