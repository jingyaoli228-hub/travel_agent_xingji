// 无行程状态（行程页即首页）：插画 hero + 快捷提示词。点提示词 → 填入 chat-bar 或直接发送
Component({
  properties: {
    kicker: { type: String, value: '行迹 · 你的旅行搭子' },
    title: { type: String, value: '想去哪儿？' },
    sub: { type: String, value: '一句话告诉我，Agent 帮你排好每一天' },
    prompts: { type: Array, value: ['北京 3 天，带爸妈不赶路', '周末杭州 citywalk', '粘贴小红书笔记导入'] }
  },
  methods: { onPrompt(e) { this.triggerEvent('prompt', { text: e.currentTarget.dataset.text }); } }
});
