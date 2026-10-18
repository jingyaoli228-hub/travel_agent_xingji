Component({
  properties: {
    type: { type: String, value: 'card' }, // card | text | map
    rows: { type: Number, value: 3 },
    height: { type: Number, value: 400 },  // map 高度 rpx
    animate: { type: Boolean, value: true }
  },
  data: { rowsArr: [0, 1, 2] },
  observers: { rows(n) { this.setData({ rowsArr: Array.from({ length: Math.max(1, n) }, (_, i) => i) }); } }
});
