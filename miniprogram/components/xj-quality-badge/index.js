// 行程质量评审徽标（与餐厅评分 xj-score-chip 区分）。点击 → 打开 Agent 透视面板
Component({
  properties: {
    score: { type: Number, value: 0 },
    label: { type: String, value: '评审' },
    status: { type: String, value: 'auto' }, // auto(按分数) | pass | draft | fail
    passLine: { type: Number, value: 85 }
  },
  data: { state: 'draft' },
  observers: {
    'score, status, passLine'(score, status, passLine) {
      const state = status !== 'auto' ? status : (score >= passLine ? 'pass' : 'draft');
      this.setData({ state });
    }
  },
  methods: { onTap() { this.triggerEvent('tap', { score: this.data.score, state: this.data.state }); } }
});
