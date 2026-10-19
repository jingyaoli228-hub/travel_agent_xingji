const api = require('../../utils/api')

const STYLE_OPTIONS = ['人文古迹', '博物馆', '美食', '拍照', '自然']
const PACE_OPTIONS = ['特种兵', '适中', '松弛']
const WAKE_OPTIONS = ['早起', '正常', '晚起']
const STYLE_TO_INTEREST = {
  '人文古迹': '人文', '博物馆': '人文', '美食': '美食', '拍照': '摄影', '自然': '自然'
}

function newTripId() {
  return `trip-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function flattenCandidates(candidates) {
  const groups = (candidates && candidates.experiences) || {}
  const rows = []
  Object.keys(groups).forEach(group => {
    ;(groups[group] || []).forEach(item => rows.push(Object.assign({ group, choice: 'want' }, item)))
  })
  return rows
}

function requirementDays(requirement) {
  return Number((requirement && requirement.duration_days) || 3)
}

Page({
  data: {
    navH: 64, phase: 'input', prompt: '', busy: false,
    clarificationText: '', clarificationReply: '',
    styles: STYLE_OPTIONS.map(label => ({ label, selected: false })),
    paces: PACE_OPTIONS.map(label => ({ label, selected: label === '适中' })),
    wakes: WAKE_OPTIONS.map(label => ({ label, selected: label === '正常' })),
    mustGo: '', avoid: '', profileHint: '', requirement: {},
    progressText: '正在理解需求…', progressStep: 0, daySkeletons: [],
    candidates: [], selectedCount: 0, capacity: 0, overflow: 0,
    draftDays: [], score: 0, issues: [], planningError: '',
    partialDays: []
  },

  onLoad() {
    const prompt = wx.getStorageSync('travel-agent:draft-prompt') || ''
    wx.removeStorageSync('travel-agent:draft-prompt')
    this.setData({ prompt })
    this.loadProfile()
  },

  onUnload() { this.stopProgress() },
  onNavReady(event) { this.setData({ navH: event.detail.totalHeight }) },
  goBack() { wx.navigateBack() },
  onPromptInput(event) { this.setData({ prompt: event.detail.value }) },
  onClarificationInput(event) { this.setData({ clarificationReply: event.detail.value }) },
  choosePrompt(event) { this.setData({ prompt: event.currentTarget.dataset.text }) },
  onMustInput(event) { this.setData({ mustGo: event.detail.value }) },
  onAvoidInput(event) { this.setData({ avoid: event.detail.value }) },

  async loadProfile() {
    const userId = wx.getStorageSync('travel-agent:user-id') || 'owner'
    wx.setStorageSync('travel-agent:user-id', userId)
    try {
      const context = await api.getPlanningContext(userId)
      const profile = context.profile || {}
      const interests = profile.interests || []
      const styles = this.data.styles.map(item => ({
        ...item, selected: interests.includes(STYLE_TO_INTEREST[item.label] || item.label)
      }))
      this.setData({
        styles,
        profileHint: context.prefilled ? '已按你的历史偏好预填，带「上次」的可直接确认' : ''
      })
    } catch (_) {}
  },

  toggleOption(key, index) {
    const multiple = key === 'styles'
    const rows = this.data[key].map((item, idx) => ({
      ...item, selected: multiple ? (idx === index ? !item.selected : item.selected) : idx === index
    }))
    this.setData({ [key]: rows })
  },
  toggleStyle(event) { this.toggleOption('styles', Number(event.detail.value)) },
  choosePace(event) { this.toggleOption('paces', Number(event.detail.value)) },
  chooseWake(event) { this.toggleOption('wakes', Number(event.detail.value)) },

  async submitIntent() {
    const prompt = this.data.prompt.trim()
    if (!prompt || this.data.busy) return
    const tripId = newTripId()
    const userId = wx.getStorageSync('travel-agent:user-id') || 'owner'
    this._tripId = tripId
    this.setData({ busy: true })
    try {
      const result = await api.postChat(tripId, prompt, userId)
      this.handleRequirementResult(result)
    } catch (error) {
      this.setData({ busy: false, planningError: error.message, phase: 'error' })
    }
  },

  handleRequirementResult(result) {
    const data = result.data || {}
    const requirement = data.travel_requirement || this.data.requirement || {}
    if (['clarification', 'region_confirmation'].includes(data.stage)) {
      this.setData({
        busy: false,
        phase: 'clarification',
        requirement,
        clarificationText: result.response || '还需要补充一点信息，才能继续规划。',
        clarificationReply: ''
      })
      return
    }
    const days = requirementDays(requirement)
    this.setData({
      busy: false,
      phase: 'preferences',
      requirement,
      daySkeletons: Array.from({ length: days }, (_, i) => ({ day: i + 1, ready: false }))
    })
  },

  async submitClarification() {
    const reply = this.data.clarificationReply.trim()
    if (!reply || this.data.busy || !this._tripId) return
    this.setData({ busy: true })
    try {
      const result = await api.postChat(this._tripId, reply, wx.getStorageSync('travel-agent:user-id') || 'owner')
      this.handleRequirementResult(result)
    } catch (error) {
      this.setData({ busy: false })
      wx.showToast({ title: error.message || '补充信息失败', icon: 'none' })
    }
  },

  selectedLabel(key) {
    return this.data[key].filter(item => item.selected).map(item => item.label)
  },

  async confirmPreferences() {
    if (this.data.busy) return
    const styles = this.selectedLabel('styles')
    const pace = this.selectedLabel('paces')[0] || '适中'
    const wake = this.selectedLabel('wakes')[0] || '正常'
    const interests = [...new Set(styles.map(label => STYLE_TO_INTEREST[label] || label))]
    const details = [
      interests.length ? `兴趣：${interests.join('、')}` : '', `节奏：${pace}`, `作息：${wake}`,
      this.data.mustGo.trim() ? `必去：${this.data.mustGo.trim()}` : '必去：无',
      this.data.avoid.trim() ? `不想去：${this.data.avoid.trim()}` : '不想去：无'
    ].filter(Boolean).join('；')
    wx.setStorageSync('travel-agent:last-preferences', { styles, pace, wake })
    this.setData({ busy: true, phase: 'planning', progressText: '正在准备目的地资料…' })
    this.startProgress()
    try {
      // First persist the edits, then confirm in a separate turn. Sending
      // “修改 + 确认” in one message made the confirmation node skip every
      // chip and must-go field on real devices.
      let result = await api.postChat(this._tripId, `请更新本次需求：${details}。`, wx.getStorageSync('travel-agent:user-id'))
      if ((result.data && result.data.stage) === 'confirmation') {
        result = await api.postChat(this._tripId, '确认，按以上信息开始搜索和规划。', wx.getStorageSync('travel-agent:user-id'))
      }
      await this.advance(result)
    } catch (error) { this.showPlanningError(error) }
  },

  startProgress() {
    this.stopProgress()
    const labels = ['正在理解偏好…', '正在搜索高德地点与攻略…', '正在匹配路线与开放时间…', '正在按天安排行程…', '正在进行质量评审…']
    this._progressTimer = setInterval(() => {
      const next = Math.min(this.data.progressStep + 1, labels.length - 1)
      const skeletons = this.data.daySkeletons.map((row, index) => ({ ...row, ready: index < Math.max(0, next - 2) }))
      this.setData({ progressStep: next, progressText: labels[next], daySkeletons: skeletons })
    }, 2400)
  },

  stopProgress() { if (this._progressTimer) clearInterval(this._progressTimer) },

  async waitResearch() {
    for (let attempt = 0; attempt < 90; attempt += 1) {
      await new Promise(resolve => setTimeout(resolve, 2000))
      const status = await api.getResearchStatus(this._tripId)
      const done = Object.values(status.progress || {}).filter(value => value === 'done').length
      const total = Math.max(Object.keys(status.progress || {}).length, 1)
      this.setData({ progressText: `正在准备目的地资料… ${done}/${total}` })
      if (status.status === 'error') throw new Error(status.error || '资料准备失败')
      if (status.status === 'done' || status.status === 'idle') return api.getSession(this._tripId)
    }
    throw new Error('资料准备超时，请稍后重试')
  },

  async advance(result) {
    const data = result.data || {}
    const stage = data.stage
    if (stage === 'researching' || stage === 'research') return this.advance(await this.waitResearch())
    if (stage === 'selection') {
      const candidates = flattenCandidates(data.candidates)
      const days = requirementDays(data.travel_requirement || this.data.requirement)
      const dailyCount = Number((data.travel_requirement && data.travel_requirement.daily_attraction_count) || 3)
      const capacity = days * dailyCount + days * 2
      const mustNames = this.data.mustGo.split(/[、,，]/).map(value => value.trim()).filter(Boolean)
      if (candidates.length > capacity) {
        const rows = candidates.map(item => ({ ...item, choice: mustNames.some(name => item.name.includes(name)) ? 'must' : 'want' }))
        this.stopProgress()
        this.setData({
          phase: 'selection', busy: false, candidates: rows,
          selectedCount: rows.filter(item => item.choice !== 'exclude').length,
          capacity, overflow: Math.max(rows.filter(item => item.choice !== 'exclude').length - capacity, 0)
        })
        return
      }
      const planned = await api.postChat(this._tripId, '按推荐自动选择并生成草稿行程。', wx.getStorageSync('travel-agent:user-id'))
      return this.advance(planned)
    }
    if (['done', 'post_plan_feedback'].includes(stage) || data.itinerary || data.final_plan) {
      this.stopProgress()
      const finalPlan = data.final_plan || {}
      const itinerary = data.itinerary || finalPlan.itinerary || {}
      const review = data.review_report || {}
      const score = Math.round(Number(review.score || 0))
      wx.setStorageSync('travel-agent:active-trip-id', this._tripId)
      wx.setStorageSync('travel-agent:session-id', this._tripId)
      this.setData({
        phase: 'draft', busy: false, draftDays: itinerary.days || [], score,
        issues: review.issues || [], progressText: score >= 85 ? `评审 ${score}/100` : `草稿 · 质量 ${score}/100`
      })
      return
    }
    if (stage === 'planning') return
    throw new Error(result.response || '规划未能继续')
  },

  cycleChoice(event) {
    const index = Number(event.currentTarget.dataset.index)
    const order = ['must', 'want', 'optional', 'exclude']
    const candidates = this.data.candidates.map((item, idx) => idx === index
      ? { ...item, choice: order[(order.indexOf(item.choice) + 1) % order.length] } : item)
    const selectedCount = candidates.filter(item => item.choice !== 'exclude').length
    this.setData({ candidates, selectedCount, overflow: Math.max(selectedCount - this.data.capacity, 0) })
  },

  async submitSelection(event) {
    if (this.data.busy) return
    const recommended = event.currentTarget.dataset.mode === 'recommended'
    if (recommended) {
      this.setData({ phase: 'planning', busy: true, progressText: 'Agent 正在按全面性筛选并生成草稿…' })
      this.startProgress()
      try {
        await this.advance(await api.postChat(
          this._tripId, '按推荐自动选择并生成草稿行程。', wx.getStorageSync('travel-agent:user-id')
        ))
      } catch (error) { this.showPlanningError(error) }
      return
    }
    let chosen = this.data.candidates.filter(item => item.choice !== 'exclude')
    const waitlist = this.data.candidates.filter(item => !chosen.some(row => row.name === item.name)).map(item => item.name)
    const message = `选择这些地点：${chosen.map(item => item.name).join('、')}。${waitlist.length ? `其余放入候补：${waitlist.join('、')}。` : ''}请生成草稿。`
    this.setData({ phase: 'planning', busy: true, progressText: '正在按选择生成草稿…' })
    this.startProgress()
    try { await this.advance(await api.postChat(this._tripId, message, wx.getStorageSync('travel-agent:user-id'))) }
    catch (error) { this.showPlanningError(error) }
  },

  async autoFix() {
    if (this.data.busy) return
    this.setData({ busy: true, phase: 'planning', progressText: '正在按评审问题自动修正…' })
    this.startProgress()
    try {
      const userId = wx.getStorageSync('travel-agent:user-id')
      let result = await api.postChat(this._tripId, '请根据评审问题自动修正行程，仍不达标时保留草稿并列出问题。', userId)
      if (result.need_user_input && result.current_node === 'clarify_post_plan') {
        result = await api.postChat(
          this._tripId,
          '直接按评审建议修正：不改目的地、日期、预算、必去和不想去；新增内容优先，装不下的放候补，无需再次确认。',
          userId
        )
      }
      await this.advance(result)
    }
    catch (error) { this.showPlanningError(error) }
  },

  showPlanningError(error) {
    this.stopProgress()
    this.setData({ busy: false, phase: 'error', planningError: error.message || '规划失败' })
    api.getSession(this._tripId).then(result => {
      const itinerary = (result.data && (result.data.itinerary || (result.data.final_plan || {}).itinerary)) || {}
      this.setData({ partialDays: itinerary.days || [] })
    }).catch(() => {})
  },

  retry() { this.confirmPreferences() },
  editRequest() { this.stopProgress(); this.setData({ phase: 'input', busy: false }) },
  openTrip() { wx.reLaunch({ url: '/pages/itinerary/index' }) }
})
