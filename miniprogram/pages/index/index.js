const api = require("../../utils/api")

const RESEARCH_STAGES = ["research", "researching", "planning"]
const STAGE_LABELS = {
  requirement: "需求确认", clarification: "补充信息", region_confirmation: "地区确认", confirmation: "信息确认",
  selection: "挑选体验", research: "资料调研", researching: "资料调研",
  planning: "生成行程", done: "规划完成", failed: "需要重试"
}
const CATEGORY_LABELS = {
  landmark: "地标", culture: "文化", architecture: "建筑", shopping: "购物",
  food: "美食", local_life: "本地生活", nightlife: "夜生活", photography: "摄影",
  workshop: "体验", music: "音乐"
}

function uuid() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function storedIdentity() {
  let sessionId = wx.getStorageSync("travel-agent:session-id")
  let userId = wx.getStorageSync("travel-agent:user-id")
  if (!sessionId) { sessionId = `wx-${uuid()}`; wx.setStorageSync("travel-agent:session-id", sessionId) }
  if (!userId) { userId = `wx-user-${uuid()}`; wx.setStorageSync("travel-agent:user-id", userId) }
  return { sessionId, userId }
}

Page({
  data: {
    sessionId: "",
    userId: "",
    input: "",
    messages: [{ id: "welcome", role: "assistant", content: "你好，我是行迹。告诉我想去哪里、几天、几个人和大致预算，我会一步步和你确认。" }],
    stage: "requirement",
    stageLabel: "需求确认",
    quickPrompts: [
      { icon: "⛰", title: "自然漫游", text: "帮我规划一次轻松的自然风光旅行" },
      { icon: "⌖", title: "城市探索", text: "我想深度探索一座城市的文化与街区" },
      { icon: "♨", title: "寻味之旅", text: "帮我安排一趟以当地美食为主的旅行" }
    ],
    requirement: null,
    candidateGroups: [],
    itineraryDays: [],
    researchItems: [],
    warnings: [],
    activeTab: "chat",
    busy: false,
    polling: false,
    error: ""
  },

  onLoad() {
    const identity = storedIdentity()
    this.setData(identity)
    this.restoreSession()
  },

  onUnload() { this.stopPolling() },

  onInput(event) { this.setData({ input: event.detail.value }) },
  setTab(event) { this.setData({ activeTab: event.currentTarget.dataset.tab }) },
  selectQuickPrompt(event) { this.setData({ input: event.currentTarget.dataset.prompt }) },

  async restoreSession() {
    try {
      const result = await api.getSession(this.data.sessionId)
      this.applyPayload(result.data || {})
      if (result.response) this.appendMessage("assistant", result.response)
    } catch (_) {
      // 404 means a fresh local session; no UI error is needed.
    }
  },

  async sendMessage() {
    const text = this.data.input.trim()
    if (!text || this.data.busy) return
    this.appendMessage("user", text)
    this.setData({ input: "", busy: true, error: "" })
    try {
      const result = await api.postChat(this.data.sessionId, text, this.data.userId)
      this.appendMessage("assistant", result.response || "已收到。")
      this.applyPayload(result.data || {})
      if (RESEARCH_STAGES.includes((result.data || {}).stage)) this.startPolling()
    } catch (error) {
      this.setData({ error: error.message || "请求失败，请稍后再试" })
    } finally {
      this.setData({ busy: false })
    }
  },

  appendMessage(role, content) {
    if (!content) return
    const messages = this.data.messages.concat({ id: uuid(), role, content })
    this.setData({ messages })
    setTimeout(() => this.setData({ scrollTo: `msg-${messages[messages.length - 1].id}` }), 30)
  },

  applyPayload(data) {
    const groups = []
    const experiences = (data.candidates && data.candidates.experiences) || {}
    Object.keys(experiences).forEach((key) => {
      groups.push({ key, label: CATEGORY_LABELS[key] || key, items: experiences[key] || [] })
    })
    const plan = data.final_plan || {}
    const itinerary = data.itinerary || plan.itinerary || {}
    const itineraryDays = (itinerary.days || this.data.itineraryDays).map((day) => ({
      ...day,
      items: (day.items || []).map((item) => ({
        ...item,
        displayLocation: (item.location || item.name || "").replace(/\s*\([^)]*\)\s*$/, "")
      }))
    }))
    const requirement = data.travel_requirement || this.data.requirement
    const warnings = (plan.notes || []).filter((item) => /不可用|失败|估算|复核|占位/.test(item))
    this.setData({
      stage: data.stage || this.data.stage,
      stageLabel: STAGE_LABELS[data.stage] || this.data.stageLabel,
      requirement,
      candidateGroups: groups.length ? groups : this.data.candidateGroups,
      itineraryDays,
      warnings
    })
  },

  startPolling() {
    if (this.data.polling) return
    this.setData({ polling: true })
    this.pollResearch()
  },

  stopPolling() {
    if (this.pollTimer) clearTimeout(this.pollTimer)
    this.pollTimer = null
    if (this.data.polling) this.setData({ polling: false })
  },

  async pollResearch() {
    if (!this.data.polling) return
    try {
      const status = await api.getResearchStatus(this.data.sessionId)
      const items = Object.keys(status.progress || {}).map((key) => ({ key, state: status.progress[key] }))
      this.setData({ researchItems: items })
      if (status.status === "done" || status.status === "error") {
        const session = await api.getSession(this.data.sessionId)
        this.applyPayload(session.data || {})
        if (session.response) this.appendMessage("assistant", session.response)
        if (status.error) this.setData({ error: status.error })
        this.stopPolling()
        return
      }
    } catch (_) {}
    this.pollTimer = setTimeout(() => this.pollResearch(), 1500)
  },

  resetSession() {
    wx.showModal({
      title: "开始新规划？",
      content: "当前页面里的对话将清空，云端历史不会被删除。",
      success: (result) => {
        if (!result.confirm) return
        this.stopPolling()
        const sessionId = `wx-${uuid()}`
        wx.setStorageSync("travel-agent:session-id", sessionId)
        this.setData({
          sessionId, input: "", stage: "requirement", stageLabel: "需求确认", requirement: null,
          candidateGroups: [], itineraryDays: [], researchItems: [], warnings: [], error: "",
          activeTab: "chat",
          messages: [{ id: "welcome", role: "assistant", content: "新的规划已开始。告诉我这次想去哪里吧。" }]
        })
      }
    })
  }
})
