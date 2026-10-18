// 小红书粘贴导入解析结果卡
Component({
  properties: {
    source: { type: String, value: '小红书' },
    title: { type: String, value: '' },
    places: { type: Array, value: [] },     // [{ name, note, matched:true|false, checked:true|false }]
    confirmText: { type: String, value: '加入想去清单' }
  },
  data: { matched: 0 },
  observers: { places(p) { this.setData({ matched: (p || []).filter(x => x.matched).length }); } },
  methods: {
    onToggle(e) {
      const i = Number(e.currentTarget.dataset.index); const p = this.data.places[i];
      if (!p || !p.matched) return;
      this.setData({ [`places[${i}].checked`]: p.checked === false });
      this.triggerEvent('change', { index: i, checked: p.checked === false });
    },
    onFix(e) { this.triggerEvent('fix', { index: Number(e.currentTarget.dataset.index) }); },
    onOrigin() { this.triggerEvent('origin', {}); },
    onConfirm() { this.triggerEvent('confirm', { places: this.data.places.filter(x => x.matched && x.checked !== false) }); }
  }
});
