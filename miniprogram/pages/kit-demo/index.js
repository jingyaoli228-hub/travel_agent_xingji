Page({
  data: {
    colors: [
      { name: '主色', hex: '#1E3A6E' }, { name: 'CTA 橙', hex: '#C2410C' }, { name: '地图橙', hex: '#FF7A45' }, { name: '背景', hex: '#F7F5F0' },
      { name: '文字', hex: '#1B2333' }, { name: '次文字', hex: '#5F6878' }, { name: '三级文字', hex: '#666E7D' }, { name: '锁定', hex: '#1F7A52' }
    ],
    chips: [
      { label: '历史人文', status: 'selected' }, { label: '自然风光', status: 'default' },
      { label: '必去 · 故宫', status: 'must', closable: true }, { label: '排除 · 购物', status: 'exclude', closable: true }
    ],
    days: [{ label: 'Day 1', sub: '周六', today: true }, { label: 'Day 2', sub: '周日', warn: true }, { label: 'Day 3', sub: '周一' }],
    day: 0, log: '', nodeExp: false,
    alerts: [
      { id: 'r1', type: 'risk', text: '周日下午有雷阵雨', actionText: '看备选' },
      { id: 'q1', type: 'quality', text: '评审 78 分：Day2 步行偏多', actionText: '看透视' },
      { id: 'e1', type: 'degraded', text: '路线服务降级，交通时间为估算', actionText: '重试' }
    ],
    alerts2: [{ id: 'q', type: 'quality', text: '还差 7 分达标：午餐未定', actionText: '去补全' }, { id: 'r', type: 'risk', text: '国博需提前 3 天预约' }],
    steps: [
      { title: '东门进 · 祈年殿', desc: '先看主殿，避开旅行团', time: '40min' },
      { title: '丹陛桥 → 皇穹宇 · 回音壁', time: '30min' },
      { title: '圜丘坛', desc: '站天心石拍照', time: '20min' },
      { title: '支线：神乐署', desc: '+30min，会重算当天', time: '可选', branch: true }
    ],
    impacts: [
      { text: '前门大街顺延 40 分钟', level: 'warn' }, { text: '晚餐 四季民福 预约 18:00 将赶不上', level: 'error' }, { text: '步行增加 1.2km', level: 'info' }
    ],
    places: [
      { name: '天坛公园', note: '笔记提到：早上 8 点前人少', matched: true },
      { name: '四季民福（前门店）', note: '烤鸭 · 人均 180', matched: true },
      { name: '“那家胡同里的咖啡”', note: '未能确定具体地点', matched: false }
    ],
    trips: [
      { city: '北京', dates: '10/24 - 10/26', days: 3, status: 'draft', summary: '评审 78' },
      { city: '杭州', dates: '11/02 - 11/04', days: 3, status: 'confirmed', summary: '12 个地点', cover: 'linear-gradient(135deg,#3D5F9C,#FF9A6B)' },
      { city: '成都', dates: '10/17 - 10/19', days: 3, status: 'ongoing', cover: 'linear-gradient(135deg,#1F7A52,#2F5597)' },
      { city: '厦门', dates: '09/12 - 09/14', days: 3, status: 'traveled', cover: 'linear-gradient(135deg,#9AA1AD,#5F6878)' }
    ],
    markerIcons: ['poi-orange-1', 'poi-navy-2', 'restaurant', 'restaurant-orange', 'hotel', 'current']
  },
  setLog(s) { this.setData({ log: s }); },
  goMap() { wx.navigateTo({ url: '/pages/kit-map/index' }); },
  onBtn() { this.setLog('button tap'); },
  onChip(e) {
    const i = e.detail.value; const c = this.data.chips[i];
    if (c.status === 'default' || c.status === 'selected') this.setData({ [`chips[${i}].status`]: c.status === 'selected' ? 'default' : 'selected' });
    this.setLog('chip tap ' + c.label);
  },
  onChipClose(e) { this.setLog('chip close ' + this.data.chips[e.detail.value].label); },
  onQuality(e) { this.setLog('quality tap → 打开透视面板 ' + e.detail.state + ' ' + e.detail.score); },
  onDay(e) { this.setData({ day: e.detail.index }); },
  onAlert(e) { this.setLog('action ' + JSON.stringify(e.detail || {})); },
  onCard(e) { this.setLog('card tap ' + e.detail.id); },
  onCardLong(e) { this.setLog('card longpress ' + e.detail.id); },
  onSlot() { this.setLog('empty slot tap → 打开餐厅候选'); },
  onExpand(e) { this.setData({ nodeExp: e.detail.expanded }); },
  onNodeAct(e) {
    this.setLog('node ' + e.detail.act);
    if (e.detail.act === 'delete') this.selectComponent('#toast').show({ text: '已删除 天坛公园', actionText: '撤销', payload: { id: 1 } });
  },
  onForce() { this.setLog('force → 该节点 itinerary-card 设置 conflict 原因'); },
  onImport(e) { this.setLog('import ' + e.detail.places.length + ' 个'); },
  onOrigin() { this.setLog('origin → 复制链接 + toast「已复制，到小红书粘贴打开」'); },
  onTrip(e) { this.setLog('trip ' + e.detail.id); },
  onPrompt(e) { this.setLog('prompt: ' + e.detail.text); },
  onSend(e) { this.setLog('send: ' + e.detail.value); },
  showToast() { this.selectComponent('#toast').show({ text: '已把前门大街移到 Day 2', actionText: '撤销', payload: { op: 'move' } }); },
  onUndo(e) { this.setLog('undo ' + JSON.stringify(e.detail.payload)); }
});
