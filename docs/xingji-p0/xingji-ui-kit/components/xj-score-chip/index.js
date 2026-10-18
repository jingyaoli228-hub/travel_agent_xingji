// 仅用于餐厅/POI 第三方评分（中性灰，不用橙色）。行程质量请用 xj-quality-badge
Component({
  properties: {
    score: { type: null, value: '' },   // 4.7
    suffix: { type: String, value: '' } // 如 '大众点评'
  },
  methods: { onTap() { this.triggerEvent('tap', { score: this.data.score }); } }
});
