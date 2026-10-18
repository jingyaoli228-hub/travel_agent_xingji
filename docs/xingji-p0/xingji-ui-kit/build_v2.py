# ---- v2 components (executed inside build_kit.py namespace: w, comp, json, C) ----
def cjson(name,deps=None):
    w(f'components/{name}/index.json',json.dumps({"component":True,"styleIsolation":"apply-shared","usingComponents":deps or {}},indent=2))

comp('xj-nav-bar','''<view class="xj-nav" style="padding-top:{{statusBarHeight}}px;background:{{bg}}">
  <view class="xj-nav__bar" style="height:{{navHeight}}px;padding-right:{{capsuleSpace}}px">
    <view wx:if="{{showLeft}}" class="xj-nav__left" hover-class="xj-nav__left--hover" bindtap="onLeft"><view class="xj-icon xj-icon--list-navy"></view><text>{{leftText}}</text></view>
    <view class="xj-nav__title"><text class="xj-nav__t">{{title}}</text><text wx:if="{{subtitle}}" class="xj-nav__s">{{subtitle}}</text></view>
    <slot></slot>
  </view>
</view>
<view wx:if="{{placeholder}}" style="height:{{totalHeight}}px"></view>''','''.xj-nav{position:fixed;top:0;left:0;right:0;z-index:var(--xj-z-nav)}
.xj-nav__bar{display:flex;align-items:center;padding-left:24rpx;box-sizing:border-box;gap:16rpx}
.xj-nav__left{display:flex;align-items:center;gap:8rpx;height:60rpx;padding:0 20rpx 0 16rpx;border-radius:var(--xj-radius-pill);background:var(--xj-card);box-shadow:0 4rpx 16rpx rgba(20,30,50,.08);font-size:var(--xj-font-caption);font-weight:700;color:var(--xj-primary);--xj-icon-size:30rpx;flex-shrink:0}
.xj-nav__left--hover{opacity:.8}
.xj-nav__title{flex:1;min-width:0;display:flex;flex-direction:column}
.xj-nav__t{font-size:var(--xj-font-h3);font-weight:700;color:var(--xj-text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.xj-nav__s{font-size:var(--xj-font-mini);color:var(--xj-text2)}''','''// 自定义导航栏：页面 json 需 "navigationStyle": "custom"
// 依据 wx.getMenuButtonBoundingClientRect 对齐胶囊，右侧胶囊区域不放任何内容
Component({
  properties: {
    title: { type: String, value: '' },
    subtitle: { type: String, value: '' },
    leftText: { type: String, value: '我的行程' },
    showLeft: { type: Boolean, value: true },
    bg: { type: String, value: 'transparent' },   // 地图页透明；列表页可传 '#F7F5F0'
    placeholder: { type: Boolean, value: false }  // 是否占位（非地图页设 true）
  },
  data: { statusBarHeight: 20, navHeight: 44, capsuleSpace: 96, totalHeight: 64 },
  lifetimes: {
    attached() {
      try {
        const win = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
        const sb = win.statusBarHeight || 20;
        const m = wx.getMenuButtonBoundingClientRect();
        const navHeight = m && m.height ? (m.top - sb) * 2 + m.height : 44;
        const capsuleSpace = m && m.left ? win.windowWidth - m.left + 8 : 96;
        this.setData({ statusBarHeight: sb, navHeight, capsuleSpace, totalHeight: sb + navHeight });
        this.triggerEvent('ready', { statusBarHeight: sb, navHeight, totalHeight: sb + navHeight });
      } catch (e) { /* 使用默认值 */ }
    }
  },
  methods: { onLeft() { this.triggerEvent('left', {}); } }
});''')

comp('xj-quality-badge','''<view class="xj-qb xj-qb--{{state}}" hover-class="xj-qb--hover" bindtap="onTap">
  <view class="xj-icon xj-icon--{{state==='pass'?'shield-green':(state==='draft'?'clock-amber':'error-red')}}"></view>
  <text wx:if="{{state==='draft'}}" class="xj-qb__tag">草稿</text>
  <text wx:elif="{{state==='fail'}}" class="xj-qb__tag">未通过</text>
  <text class="xj-qb__l">{{label}}</text><text class="xj-qb__n">{{score}}</text>
  <view class="xj-icon xj-icon--chevron-grey xj-qb__c"></view>
</view>''','''.xj-qb{display:inline-flex;align-items:center;gap:8rpx;height:60rpx;padding:0 14rpx 0 18rpx;border-radius:var(--xj-radius-pill);background:var(--xj-card);box-shadow:0 4rpx 16rpx rgba(20,30,50,.10);font-size:var(--xj-font-caption);color:var(--xj-text2);--xj-icon-size:28rpx;white-space:nowrap}
.xj-qb--hover{opacity:.85}
.xj-qb__n{font-size:var(--xj-font-h3);font-weight:700;color:var(--xj-primary)}
.xj-qb__tag{padding:0 10rpx;border-radius:8rpx;font-size:var(--xj-font-mini);font-weight:700;line-height:34rpx}
.xj-qb--draft .xj-qb__tag{background:var(--xj-warn-light);color:var(--xj-warn-text)}.xj-qb--draft .xj-qb__n{color:var(--xj-warn-text)}
.xj-qb--fail .xj-qb__tag{background:var(--xj-error-light);color:var(--xj-error)}.xj-qb--fail .xj-qb__n{color:var(--xj-error)}
.xj-qb__c{--xj-icon-size:22rpx}''','''// 行程质量评审徽标（与餐厅评分 xj-score-chip 区分）。点击 → 打开 Agent 透视面板
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
});''')

comp('xj-alert-bar','''<view wx:if="{{top}}" class="xj-alert xj-alert--{{top.tone}}">
  <view class="xj-alert__main">
    <view class="xj-icon xj-icon--{{top.icon}}"></view>
    <text class="xj-alert__text">{{top.text}}</text>
    <text wx:if="{{top.actionText}}" class="xj-alert__act" data-id="{{top.id}}" bindtap="onAction">{{top.actionText}}</text>
    <view wx:if="{{rest.length}}" class="xj-alert__more" bindtap="toggle"><text>{{expanded?'收起':(list.length+' 条提醒')}}</text><view class="xj-icon xj-icon--{{expanded?'up':'chevron'}}-dark"></view></view>
    <view wx:elif="{{closable}}" class="xj-alert__close" data-id="{{top.id}}" bindtap="onClose"><view class="xj-icon xj-icon--close-grey"></view></view>
  </view>
  <view wx:if="{{expanded}}" class="xj-alert__list">
    <view wx:for="{{rest}}" wx:key="id" class="xj-alert__row">
      <view class="xj-icon xj-icon--{{item.icon}}"></view><text class="xj-alert__text">{{item.text}}</text>
      <text wx:if="{{item.actionText}}" class="xj-alert__act" data-id="{{item.id}}" bindtap="onAction">{{item.actionText}}</text>
    </view>
  </view>
</view>''','''.xj-alert{border-radius:var(--xj-radius-sm);font-size:var(--xj-font-sm);--xj-icon-size:32rpx;overflow:hidden}
.xj-alert__main,.xj-alert__row{display:flex;align-items:center;gap:16rpx;padding:20rpx 24rpx}
.xj-alert__row{border-top:2rpx solid rgba(0,0,0,.06)}
.xj-alert--error{background:var(--xj-error-light);color:var(--xj-error)}
.xj-alert--warn{background:var(--xj-warn-light);color:var(--xj-warn-text)}
.xj-alert--info{background:var(--xj-info-light);color:var(--xj-primary)}
.xj-alert__text{flex:1;min-width:0}
.xj-alert__act{font-weight:700;color:var(--xj-primary);flex-shrink:0}
.xj-alert__more{display:flex;align-items:center;gap:4rpx;flex-shrink:0;font-size:var(--xj-font-caption);color:var(--xj-text2);--xj-icon-size:24rpx;padding-left:16rpx;border-left:2rpx solid rgba(0,0,0,.08)}
.xj-alert__close{display:flex;--xj-icon-size:26rpx}''','''// 单一提醒位：传 alerts 数组，按优先级只显示一条，其余折叠为「N 条提醒」
// 优先级：error / degraded / offline(1) > quality(2) > risk(3) > info(4)
const META = {
  error: { p: 1, tone: 'error', icon: 'error-red' },
  degraded: { p: 1, tone: 'error', icon: 'warn-red' },
  offline: { p: 1, tone: 'error', icon: 'offline-red' },
  quality: { p: 2, tone: 'warn', icon: 'shield-amber' },
  risk: { p: 3, tone: 'warn', icon: 'warn-amber' },
  warn: { p: 3, tone: 'warn', icon: 'warn-amber' },
  info: { p: 4, tone: 'info', icon: 'info-blue' }
};
Component({
  properties: {
    alerts: { type: Array, value: [] }, // [{ id, type:'error'|'degraded'|'offline'|'quality'|'risk'|'info', text, actionText }]
    type: { type: String, value: '' },  // 兼容单条用法
    text: { type: String, value: '' },
    actionText: { type: String, value: '' },
    closable: { type: Boolean, value: false }
  },
  data: { list: [], top: null, rest: [], expanded: false },
  observers: {
    'alerts, type, text, actionText'(alerts, type, text, actionText) {
      let src = (alerts && alerts.length) ? alerts : (text ? [{ id: 'single', type: type || 'risk', text, actionText }] : []);
      const list = src.map((a, i) => {
        const m = META[a.type] || META.info;
        return Object.assign({ id: a.id != null ? a.id : i }, a, { tone: m.tone, icon: m.icon, p: m.p, i });
      }).sort((x, y) => x.p - y.p || x.i - y.i);
      this.setData({ list, top: list[0] || null, rest: list.slice(1), expanded: list.length > 1 ? this.data.expanded : false });
    }
  },
  methods: {
    toggle() { this.setData({ expanded: !this.data.expanded }); this.triggerEvent('toggle', { expanded: this.data.expanded }); },
    onAction(e) { const id = e.currentTarget.dataset.id; this.triggerEvent('action', { id, alert: this.data.list.find(a => a.id === id) }); },
    onClose(e) { this.triggerEvent('close', { id: e.currentTarget.dataset.id }); }
  }
});''')

comp('xj-bottom-sheet','''<view class="xj-sheet {{dragging?'is-drag':''}}" style="height:{{fullH}}px;transform:translateY({{y}}px)">
  <view class="xj-sheet__head" catchtouchstart="onStart" catchtouchmove="onMove" catchtouchend="onEnd" catchtouchcancel="onEnd">
    <view class="xj-sheet__handle"></view>
    <slot name="header"></slot>
  </view>
  <scroll-view class="xj-sheet__body" scroll-y="{{level==='full'||scrollAlways}}" enhanced show-scrollbar="{{false}}" style="height:{{bodyH}}px" bindscrolltolower="onLower">
    <slot></slot>
    <view style="height:{{bottomPad}}rpx"></view>
  </scroll-view>
</view>''','''.xj-sheet{position:fixed;left:0;right:0;bottom:0;z-index:var(--xj-z-sheet);background:var(--xj-bg);border-radius:var(--xj-radius-lg) var(--xj-radius-lg) 0 0;box-shadow:0 -12rpx 40rpx rgba(20,30,50,.10);transition:transform .28s cubic-bezier(.2,.8,.2,1);will-change:transform}
.xj-sheet.is-drag{transition:none}
.xj-sheet__head{padding:16rpx 32rpx 8rpx}
.xj-sheet__handle{width:72rpx;height:8rpx;border-radius:4rpx;background:var(--xj-line);margin:0 auto 16rpx}
.xj-sheet__body{padding:0 32rpx;box-sizing:border-box}''','''// 三档抽屉：peek / half / full。仅「把手 + header 插槽（放 Day Tab）」可拖，列表区只滚动（UX 手势规则）
Component({
  options: { multipleSlots: true },
  properties: {
    level: { type: String, value: 'half' },   // peek | half | full（受控，可外部改）
    peekHeight: { type: Number, value: 300 }, // rpx，露出高度
    halfRatio: { type: Number, value: 0.52 }, // 半屏占窗口高度比例
    topOffset: { type: Number, value: 0 },    // px，full 时距顶（传 nav-bar 的 totalHeight）
    headerHeight: { type: Number, value: 160 },// rpx，头部估算高度（计算滚动区）
    bottomPad: { type: Number, value: 180 },  // rpx，列表底部留白（为 chat-bar 让位）
    scrollAlways: { type: Boolean, value: false }
  },
  data: { y: 0, fullH: 600, bodyH: 400, dragging: false },
  lifetimes: {
    attached() {
      const win = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
      this._rpx = win.windowWidth / 750;
      this._winH = win.windowHeight;
      this.layout();
    }
  },
  observers: { 'level, topOffset, peekHeight, halfRatio'() { if (this._winH) this.layout(); } },
  methods: {
    snaps() {
      const fullH = this._winH - this.data.topOffset;
      return { fullH, full: 0, half: fullH - this._winH * this.data.halfRatio, peek: fullH - this.data.peekHeight * this._rpx };
    },
    layout() {
      const s = this.snaps();
      this.setData({ fullH: s.fullH, bodyH: s.fullH - this.data.headerHeight * this._rpx, y: s[this.data.level] != null ? s[this.data.level] : s.half });
    },
    onStart(e) { this._sy = e.touches[0].clientY; this._y0 = this.data.y; this._t0 = Date.now(); this.setData({ dragging: true }); },
    onMove(e) {
      const s = this.snaps(); let y = this._y0 + e.touches[0].clientY - this._sy;
      y = Math.max(s.full, Math.min(s.peek, y));
      this.setData({ y });
    },
    onEnd() {
      const s = this.snaps(); const y = this.data.y; const v = (y - this._y0) / Math.max(1, Date.now() - this._t0);
      const order = ['full', 'half', 'peek']; let level;
      if (Math.abs(v) > 0.6) { const cur = order.indexOf(this.data.level); level = order[Math.max(0, Math.min(2, cur + (v > 0 ? 1 : -1)))]; }
      else level = order.reduce((a, b) => Math.abs(s[b] - y) < Math.abs(s[a] - y) ? b : a);
      this.setData({ dragging: false, level, y: s[level] });
      this.triggerEvent('change', { level });
    },
    onLower() { this.triggerEvent('scrolltolower', {}); },
    setLevel(level) { this.setData({ level }); this.triggerEvent('change', { level }); }
  }
});''')

comp('xj-node-card','''<view class="xj-node {{expanded?'is-exp':''}}">
  <view class="xj-node__head">
    <view class="xj-node__idx">{{index}}</view>
    <view class="xj-node__hd">
      <view class="xj-node__row"><text class="xj-node__name">{{name}}</text><view wx:if="{{locked}}" class="xj-node__lock"><view class="xj-icon xj-icon--lock-green"></view>已锁定</view><xj-score-chip wx:if="{{rating}}" score="{{rating}}"></xj-score-chip></view>
      <text class="xj-node__meta">{{time}}<text wx:if="{{duration}}"> · {{duration}}</text><text wx:if="{{meta}}"> · {{meta}}</text></text>
    </view>
    <view class="xj-node__close" bindtap="onClose"><view class="xj-icon xj-icon--close-grey"></view></view>
  </view>
  <view wx:if="{{tip}}" class="xj-node__tip"><text class="xj-node__tipk">避坑</text>{{tip}}</view>
  <view wx:if="{{expanded}}" class="xj-node__play">
    <view class="xj-node__st">玩法 · 主线 {{playDuration}}</view>
    <view wx:for="{{steps}}" wx:key="index" class="xj-node__step"><view class="xj-node__dot {{item.branch?'is-br':''}}"></view><view class="xj-node__sb"><text class="xj-node__sn">{{item.title}}</text><text wx:if="{{item.desc}}" class="xj-node__sd">{{item.desc}}</text></view><text wx:if="{{item.time}}" class="xj-node__stime">{{item.time}}</text></view>
    <slot name="play"></slot>
  </view>
  <slot></slot>
  <view class="xj-node__acts">
    <view class="xj-node__act" data-act="lock" bindtap="onAct"><view class="xj-icon xj-icon--lock-{{locked?'green':'dark'}}"></view>{{locked?'解锁':'锁定'}}</view>
    <view class="xj-node__act" data-act="replace" bindtap="onAct"><view class="xj-icon xj-icon--refresh-dark"></view>换一个</view>
    <view class="xj-node__act" data-act="delete" bindtap="onAct"><view class="xj-icon xj-icon--trash-dark"></view>删除</view>
    <view class="xj-node__act xj-node__act--main" bindtap="onExpand"><text>{{expanded?'收起玩法':'展开玩法'}}</text><view class="xj-icon xj-icon--{{expanded?'up':'chevron'}}-navy"></view></view>
  </view>
</view>''','''.xj-node{background:var(--xj-card);border-radius:var(--xj-radius-md);padding:28rpx;box-shadow:var(--xj-shadow-card);border:2rpx solid var(--xj-line)}
.xj-node__head{display:flex;gap:20rpx;align-items:flex-start}
.xj-node__idx{width:52rpx;height:52rpx;border-radius:50%;background:var(--xj-primary);color:#fff;font-weight:700;font-size:var(--xj-font-sm);display:flex;align-items:center;justify-content:center;flex-shrink:0}
.xj-node__hd{flex:1;min-width:0}
.xj-node__row{display:flex;align-items:center;gap:12rpx;flex-wrap:wrap}
.xj-node__name{font-size:var(--xj-font-h3);font-weight:700}
.xj-node__lock{display:inline-flex;align-items:center;gap:6rpx;height:40rpx;padding:0 14rpx;border-radius:var(--xj-radius-pill);background:var(--xj-success-light);color:var(--xj-success);font-size:var(--xj-font-mini);--xj-icon-size:22rpx}
.xj-node__meta{display:block;margin-top:6rpx;font-size:var(--xj-font-caption);color:var(--xj-text2)}
.xj-node__close{display:flex;padding:6rpx;--xj-icon-size:30rpx}
.xj-node__tip{margin-top:20rpx;padding:16rpx 20rpx;border-radius:var(--xj-radius-sm);background:var(--xj-bg);font-size:var(--xj-font-caption);color:var(--xj-text2);line-height:1.6}
.xj-node__tipk{font-weight:700;color:var(--xj-warn-text);margin-right:12rpx}
.xj-node__play{margin-top:24rpx;padding-top:24rpx;border-top:2rpx solid var(--xj-line)}
.xj-node__st{font-size:var(--xj-font-sm);font-weight:700;margin-bottom:16rpx}
.xj-node__step{display:flex;gap:16rpx;padding:12rpx 0;align-items:flex-start}
.xj-node__dot{width:16rpx;height:16rpx;border-radius:50%;background:var(--xj-primary);margin-top:12rpx;flex-shrink:0}.xj-node__dot.is-br{background:var(--xj-card);border:3rpx solid var(--xj-text3)}
.xj-node__sb{flex:1}.xj-node__sn{display:block;font-size:var(--xj-font-sm);font-weight:500}.xj-node__sd{display:block;font-size:var(--xj-font-caption);color:var(--xj-text2);margin-top:4rpx}
.xj-node__stime{font-size:var(--xj-font-caption);color:var(--xj-text3)}
.xj-node__acts{display:flex;align-items:center;gap:8rpx;margin-top:24rpx}
.xj-node__act{display:flex;align-items:center;gap:6rpx;height:60rpx;padding:0 18rpx;border-radius:var(--xj-radius-pill);background:var(--xj-bg);font-size:var(--xj-font-caption);color:var(--xj-text2);--xj-icon-size:26rpx}
.xj-node__act--main{margin-left:auto;background:var(--xj-primary-light);color:var(--xj-primary);font-weight:700}''','''// 半屏合并节点卡：点地图 marker / 列表卡片时在抽屉 half 档显示；「展开玩法」→ 页面把抽屉切到 full，并传 expanded
Component({
  options: { multipleSlots: true },
  properties: {
    index: { type: null, value: 1 },
    name: { type: String, value: '' },
    time: { type: String, value: '' },
    duration: { type: String, value: '' },
    meta: { type: String, value: '' },
    rating: { type: null, value: '' },
    locked: { type: Boolean, value: false },
    tip: { type: String, value: '' },          // 一句避坑
    expanded: { type: Boolean, value: false }, // 玩法卡（全屏）
    playDuration: { type: String, value: '' },
    steps: { type: Array, value: [] },         // [{ title, desc, time, branch }]
    itemId: { type: null, value: null }
  },
  methods: {
    onAct(e) { this.triggerEvent('action', { act: e.currentTarget.dataset.act, id: this.data.itemId }); },
    onExpand() { this.triggerEvent('expand', { expanded: !this.data.expanded, id: this.data.itemId }); },
    onClose() { this.triggerEvent('close', { id: this.data.itemId }); }
  }
});''')
cjson('xj-node-card',{"xj-score-chip":"../xj-score-chip/index"})

comp('xj-toast','''<view wx:if="{{visible}}" class="xj-toast {{leaving?'is-out':''}}" style="bottom:{{bottom}}rpx">
  <view wx:if="{{icon}}" class="xj-icon xj-icon--{{icon}}"></view>
  <text class="xj-toast__t">{{text}}</text>
  <view wx:if="{{actionText}}" class="xj-toast__act" bindtap="onAction"><view class="xj-icon xj-icon--undo-white"></view>{{actionText}}</view>
</view>''','''.xj-toast{position:fixed;left:32rpx;right:32rpx;z-index:var(--xj-z-toast);display:flex;align-items:center;gap:16rpx;min-height:88rpx;padding:16rpx 16rpx 16rpx 32rpx;border-radius:var(--xj-radius-md);background:var(--xj-text);color:#fff;font-size:var(--xj-font-sm);box-shadow:var(--xj-shadow-float);box-sizing:border-box;--xj-icon-size:32rpx;animation:xjtin .2s ease-out}
.xj-toast.is-out{opacity:0;transform:translateY(16rpx);transition:all .2s}
.xj-toast__t{flex:1;min-width:0}
.xj-toast__act{display:flex;align-items:center;gap:8rpx;height:60rpx;padding:0 22rpx;border-radius:var(--xj-radius-pill);background:rgba(255,255,255,.14);font-weight:700;--xj-icon-size:26rpx;flex-shrink:0}
@keyframes xjtin{from{opacity:0;transform:translateY(16rpx)}to{opacity:1;transform:none}}''','''// 改动提示 + 撤销。默认停留 5 秒（UX 规则），消失后撤销入口在对话记录中
Component({
  properties: {
    bottom: { type: Number, value: 180 },   // rpx，位于 chat-bar 上方
    duration: { type: Number, value: 5000 }
  },
  data: { visible: false, leaving: false, text: '', actionText: '', icon: '' },
  lifetimes: { detached() { clearTimeout(this._t); clearTimeout(this._t2); } },
  methods: {
    // this.selectComponent('#toast').show({ text:'已删除 前门大街', actionText:'撤销', payload:{...} })
    show(opt = {}) {
      clearTimeout(this._t); clearTimeout(this._t2);
      this._payload = opt.payload;
      this.setData({ visible: true, leaving: false, text: opt.text || '', actionText: opt.actionText == null ? '撤销' : opt.actionText, icon: opt.icon || '' });
      const d = opt.duration || this.data.duration;
      if (d > 0) this._t = setTimeout(() => this.hide('timeout'), d);
    },
    hide(reason = 'manual') {
      clearTimeout(this._t);
      this.setData({ leaving: true });
      this._t2 = setTimeout(() => { this.setData({ visible: false, leaving: false }); this.triggerEvent('hide', { reason, payload: this._payload }); }, 200);
    },
    onAction() { this.triggerEvent('action', { payload: this._payload }); this.hide('action'); }
  }
});''')

comp('xj-conflict-preview','''<view class="xj-cp">
  <view class="xj-cp__hd"><view class="xj-icon xj-icon--warn-amber"></view><text class="xj-cp__title">{{title}}</text></view>
  <view class="xj-cp__day"><text>{{dayLabel}}</text><text class="xj-cp__from">{{before}}</text><text class="xj-cp__arrow">→</text><text class="xj-cp__to {{over?'is-over':''}}">{{after}}</text></view>
  <view wx:for="{{impacts}}" wx:key="index" class="xj-cp__item xj-cp__item--{{item.level||'warn'}}"><view class="xj-cp__dot"></view><text>{{item.text}}</text></view>
  <slot></slot>
  <view class="xj-cp__acts">
    <view class="xj-cp__ghost" bindtap="onForce">{{forceText}}</view>
    <view class="xj-cp__btn" bindtap="onApply">{{applyText}}</view>
  </view>
</view>''','''.xj-cp{background:var(--xj-card);border-radius:var(--xj-radius-md);padding:28rpx;border:2rpx solid var(--xj-warn);box-shadow:var(--xj-shadow-card)}
.xj-cp__hd{display:flex;align-items:center;gap:12rpx;--xj-icon-size:34rpx}
.xj-cp__title{font-size:var(--xj-font-body);font-weight:700}
.xj-cp__day{display:flex;align-items:center;gap:12rpx;margin:20rpx 0 12rpx;padding:16rpx 20rpx;border-radius:var(--xj-radius-sm);background:var(--xj-bg);font-size:var(--xj-font-caption);color:var(--xj-text2)}
.xj-cp__from{text-decoration:line-through;color:var(--xj-text3)}.xj-cp__arrow{color:var(--xj-text3)}
.xj-cp__to{font-weight:700;color:var(--xj-text)}.xj-cp__to.is-over{color:var(--xj-error)}
.xj-cp__item{display:flex;align-items:flex-start;gap:12rpx;padding:8rpx 0;font-size:var(--xj-font-caption);color:var(--xj-text2);line-height:1.5}
.xj-cp__dot{width:12rpx;height:12rpx;border-radius:50%;margin-top:14rpx;flex-shrink:0;background:var(--xj-warn)}
.xj-cp__item--error .xj-cp__dot{background:var(--xj-error)}.xj-cp__item--error{color:var(--xj-error)}.xj-cp__item--info .xj-cp__dot{background:var(--xj-text3)}
.xj-cp__acts{display:flex;gap:16rpx;margin-top:24rpx}
.xj-cp__ghost,.xj-cp__btn{flex:1;height:80rpx;border-radius:var(--xj-radius-pill);display:flex;align-items:center;justify-content:center;font-size:var(--xj-font-sm);font-weight:700}
.xj-cp__ghost{background:var(--xj-primary-light);color:var(--xj-primary)}.xj-cp__btn{background:var(--xj-primary);color:#fff}''','''// 加点冲突预览：先预览，再决定。「仍然加入」后页面需把该节点 itinerary-card 设 conflict="原因"（标红，不静默）
Component({
  properties: {
    title: { type: String, value: '加入后会影响当天安排' },
    dayLabel: { type: String, value: 'Day 1 结束时间' },
    before: { type: String, value: '' },   // '18:30'
    after: { type: String, value: '' },    // '20:10'
    over: { type: Boolean, value: false }, // after 超出约束 → 红色
    impacts: { type: Array, value: [] },   // [{ text, level:'warn'|'error'|'info' }]
    applyText: { type: String, value: '按建议调整' },
    forceText: { type: String, value: '仍然加入' }
  },
  methods: {
    onApply() { this.triggerEvent('apply', {}); },
    onForce() { this.triggerEvent('force', {}); }
  }
});''')

comp('xj-offline-bar','''<view class="xj-off">
  <view class="xj-icon xj-icon--offline-white"></view>
  <view class="xj-off__b"><text class="xj-off__t">{{text}}</text><text class="xj-off__s">{{sub}}</text></view>
  <text wx:if="{{actionText}}" class="xj-off__act" bindtap="onAction">{{actionText}}</text>
</view>''','''.xj-off{display:flex;align-items:center;gap:16rpx;padding:18rpx 24rpx;border-radius:var(--xj-radius-sm);background:#3A4252;color:#fff;--xj-icon-size:34rpx}
.xj-off__b{flex:1;min-width:0;display:flex;flex-direction:column}
.xj-off__t{font-size:var(--xj-font-sm);font-weight:700}.xj-off__s{font-size:var(--xj-font-mini);opacity:.85;margin-top:2rpx}
.xj-off__act{font-size:var(--xj-font-caption);font-weight:700;padding:8rpx 20rpx;border-radius:var(--xj-radius-pill);background:rgba(255,255,255,.16)}''','''// 离线只读条：放在唯一提醒位（或用 xj-alert-bar type=offline）。离线时 chat-bar / 加地点 / 排序置灰
Component({
  properties: {
    text: { type: String, value: '离线 · 显示 10/18 14:20 的版本' },
    sub: { type: String, value: '只读模式，联网后可修改' },
    actionText: { type: String, value: '重试' }
  },
  methods: { onAction() { this.triggerEvent('retry', {}); } }
});''')

comp('xj-skeleton','''<view class="xj-sk {{animate?'is-anim':''}}">
  <block wx:if="{{type==='card'}}"><view wx:for="{{rowsArr}}" wx:key="*this" class="xj-sk__card"><view class="xj-sk__b" style="width:80rpx;height:56rpx"></view><view class="xj-sk__col"><view class="xj-sk__b" style="width:55%;height:32rpx"></view><view class="xj-sk__b" style="width:85%;height:24rpx;margin-top:16rpx"></view></view></view></block>
  <block wx:elif="{{type==='map'}}"><view class="xj-sk__b xj-sk__map" style="height:{{height}}rpx"></view></block>
  <block wx:else><view wx:for="{{rowsArr}}" wx:key="*this" class="xj-sk__b" style="height:28rpx;margin-bottom:20rpx;width:{{index===rowsArr.length-1?'60%':'100%'}}"></view></block>
</view>''','''.xj-sk__card{display:flex;gap:24rpx;padding:28rpx;border-radius:var(--xj-radius-md);background:var(--xj-card);border:2rpx solid var(--xj-line);margin-bottom:16rpx}
.xj-sk__col{flex:1}
.xj-sk__b{border-radius:var(--xj-radius-xs);background:#ECE8E0}
.xj-sk__map{border-radius:var(--xj-radius-md);width:100%}
.xj-sk.is-anim .xj-sk__b{background:linear-gradient(90deg,#ECE8E0 25%,#F5F2EC 50%,#ECE8E0 75%);background-size:400% 100%;animation:xjsk 1.4s ease infinite}
@keyframes xjsk{0%{background-position:100% 0}100%{background-position:0 0}}''','''Component({
  properties: {
    type: { type: String, value: 'card' }, // card | text | map
    rows: { type: Number, value: 3 },
    height: { type: Number, value: 400 },  // map 高度 rpx
    animate: { type: Boolean, value: true }
  },
  data: { rowsArr: [0, 1, 2] },
  observers: { rows(n) { this.setData({ rowsArr: Array.from({ length: Math.max(1, n) }, (_, i) => i) }); } }
});''')

comp('xj-empty-slot','''<view class="xj-es" hover-class="xj-es--hover" bindtap="onTap">
  <text wx:if="{{time}}" class="xj-es__time">{{time}}</text>
  <text class="xj-es__l">{{label}}</text>
  <text class="xj-es__act">{{actionText}}</text>
</view>''','''.xj-es{display:flex;align-items:center;gap:24rpx;padding:24rpx 28rpx;border-radius:var(--xj-radius-md);border:2rpx dashed var(--xj-text-disabled);background:transparent}
.xj-es--hover{background:var(--xj-card)}
.xj-es__time{width:88rpx;font-size:var(--xj-font-sm);font-weight:700;color:var(--xj-text3)}
.xj-es__l{flex:1;font-size:var(--xj-font-body);color:var(--xj-text2)}
.xj-es__act{font-size:var(--xj-font-caption);font-weight:700;color:var(--xj-primary)}''','''// 待定空位：「午餐 · 待定」，不留空
Component({
  properties: {
    label: { type: String, value: '午餐 · 待定' },
    time: { type: String, value: '' },
    actionText: { type: String, value: '去挑选 ›' },
    slotId: { type: null, value: null }
  },
  methods: { onTap() { this.triggerEvent('tap', { id: this.data.slotId }); } }
});''')

comp('xj-trip-item','''<view class="xj-ti" hover-class="xj-ti--hover" bindtap="onTap" bindlongpress="onLong">
  <view class="xj-ti__cover" style="background:{{cover||'linear-gradient(135deg,#2F5597,#1E3A6E)'}}"><text>{{days}}天</text></view>
  <view class="xj-ti__b">
    <view class="xj-ti__row"><text class="xj-ti__city">{{city}}</text><text class="xj-ti__st xj-ti__st--{{status}}">{{statusText}}</text></view>
    <text class="xj-ti__meta">{{dates}}<text wx:if="{{summary}}"> · {{summary}}</text></text>
  </view>
  <view class="xj-icon xj-icon--chevron-grey"></view>
</view>''','''.xj-ti{display:flex;align-items:center;gap:24rpx;padding:24rpx;border-radius:var(--xj-radius-md);background:var(--xj-card);border:2rpx solid var(--xj-line);--xj-icon-size:28rpx}
.xj-ti--hover{background:#FBFAF7}
.xj-ti__cover{width:104rpx;height:104rpx;border-radius:var(--xj-radius-sm);display:flex;align-items:flex-end;padding:10rpx;box-sizing:border-box;color:#fff;font-size:var(--xj-font-mini);font-weight:700;flex-shrink:0}
.xj-ti__b{flex:1;min-width:0}
.xj-ti__row{display:flex;align-items:center;gap:12rpx}
.xj-ti__city{font-size:var(--xj-font-body);font-weight:700}
.xj-ti__st{height:40rpx;line-height:40rpx;padding:0 14rpx;border-radius:var(--xj-radius-pill);font-size:var(--xj-font-mini);font-weight:700}
.xj-ti__st--draft{background:var(--xj-warn-light);color:var(--xj-warn-text)}
.xj-ti__st--confirmed{background:var(--xj-primary-light);color:var(--xj-primary)}
.xj-ti__st--ongoing{background:var(--xj-success-light);color:var(--xj-success)}
.xj-ti__st--traveled{background:#EFEDE8;color:var(--xj-text3)}
.xj-ti__meta{display:block;margin-top:8rpx;font-size:var(--xj-font-caption);color:var(--xj-text2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}''','''// 我的行程列表项。状态按日期自动判断，不让用户手动改（UX）
const TEXT = { draft: '规划中', confirmed: '待出发', ongoing: '旅行中', traveled: '已结束' };
Component({
  properties: {
    city: { type: String, value: '' },
    dates: { type: String, value: '' },     // '10/24 - 10/26'
    days: { type: Number, value: 0 },
    status: { type: String, value: 'draft' }, // draft | confirmed | ongoing | traveled
    summary: { type: String, value: '' },
    cover: { type: String, value: '' },     // CSS background，可传渐变
    tripId: { type: null, value: null }
  },
  data: { statusText: TEXT.draft },
  observers: { status(s) { this.setData({ statusText: TEXT[s] || s }); } },
  methods: {
    onTap() { this.triggerEvent('tap', { id: this.data.tripId }); },
    onLong() { this.triggerEvent('longpress', { id: this.data.tripId }); }
  }
});''')

comp('xj-import-result','''<view class="xj-ir">
  <view class="xj-ir__hd"><view class="xj-ir__src">{{source}}</view><text class="xj-ir__title">{{title}}</text></view>
  <text class="xj-ir__sum">识别到 {{places.length}} 个地点 · 已匹配 {{matched}} 个<text wx:if="{{places.length-matched>0}}">，{{places.length-matched}} 个需确认</text></text>
  <view wx:for="{{places}}" wx:key="index" class="xj-ir__p {{item.matched?'':'is-un'}}" data-index="{{index}}" bindtap="onToggle">
    <view class="xj-ir__ck {{item.checked!==false&&item.matched?'is-on':''}}"><view wx:if="{{item.checked!==false&&item.matched}}" class="xj-icon xj-icon--check-white"></view></view>
    <view class="xj-ir__pb"><text class="xj-ir__pn">{{item.name}}</text><text wx:if="{{item.note}}" class="xj-ir__pnote">{{item.note}}</text></view>
    <text wx:if="{{!item.matched}}" class="xj-ir__fix" catchtap="onFix" data-index="{{index}}">去确认</text>
  </view>
  <view class="xj-ir__acts"><view class="xj-ir__ghost" bindtap="onOrigin"><view class="xj-icon xj-icon--link-navy"></view>原笔记</view><view class="xj-ir__btn" bindtap="onConfirm">{{confirmText}}</view></view>
</view>''','''.xj-ir{background:var(--xj-card);border-radius:var(--xj-radius-md);padding:28rpx;border:2rpx solid var(--xj-line);box-shadow:var(--xj-shadow-card)}
.xj-ir__hd{display:flex;align-items:center;gap:12rpx}
.xj-ir__src{padding:0 12rpx;height:40rpx;line-height:40rpx;border-radius:8rpx;background:#FDE8EA;color:#B4233A;font-size:var(--xj-font-mini);font-weight:700;flex-shrink:0}
.xj-ir__title{flex:1;min-width:0;font-size:var(--xj-font-body);font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.xj-ir__sum{display:block;margin:12rpx 0 16rpx;font-size:var(--xj-font-caption);color:var(--xj-text2)}
.xj-ir__p{display:flex;align-items:center;gap:16rpx;padding:16rpx 0;border-top:2rpx solid var(--xj-line)}
.xj-ir__ck{width:36rpx;height:36rpx;border-radius:10rpx;border:3rpx solid var(--xj-line);display:flex;align-items:center;justify-content:center;box-sizing:border-box;--xj-icon-size:24rpx}
.xj-ir__ck.is-on{background:var(--xj-primary);border-color:var(--xj-primary)}
.xj-ir__pb{flex:1;min-width:0}.xj-ir__pn{display:block;font-size:var(--xj-font-sm);font-weight:500}.xj-ir__pnote{display:block;font-size:var(--xj-font-mini);color:var(--xj-text3);margin-top:2rpx}
.xj-ir__p.is-un .xj-ir__pn{color:var(--xj-text2)}
.xj-ir__fix{font-size:var(--xj-font-caption);font-weight:700;color:var(--xj-warn-text);background:var(--xj-warn-light);padding:6rpx 16rpx;border-radius:var(--xj-radius-pill)}
.xj-ir__acts{display:flex;gap:16rpx;margin-top:20rpx}
.xj-ir__ghost{display:flex;align-items:center;gap:8rpx;height:80rpx;padding:0 28rpx;border-radius:var(--xj-radius-pill);background:var(--xj-primary-light);color:var(--xj-primary);font-size:var(--xj-font-sm);font-weight:700;--xj-icon-size:28rpx}
.xj-ir__btn{flex:1;height:80rpx;border-radius:var(--xj-radius-pill);background:var(--xj-primary);color:#fff;display:flex;align-items:center;justify-content:center;font-size:var(--xj-font-sm);font-weight:700}''','''// 小红书粘贴导入解析结果卡
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
});''')

comp('xj-empty-state','''<view class="xj-empty">
  <view class="xj-empty__hero">
    <view class="xj-empty__sun"></view><view class="xj-empty__m1"></view><view class="xj-empty__m2"></view>
    <view class="xj-empty__ht"><text class="xj-empty__k">{{kicker}}</text><text class="xj-empty__title">{{title}}</text><text class="xj-empty__sub">{{sub}}</text></view>
  </view>
  <view class="xj-empty__chips"><view wx:for="{{prompts}}" wx:key="*this" class="xj-empty__chip" data-text="{{item}}" bindtap="onPrompt"><view class="xj-icon xj-icon--spark-navy"></view>{{item}}</view></view>
  <view class="xj-empty__acts"><slot></slot></view>
</view>''','''.xj-empty{padding:8rpx 0}
.xj-empty__hero{position:relative;height:360rpx;border-radius:var(--xj-radius-lg);overflow:hidden;background:linear-gradient(180deg,#1E3A6E 0%,#3D5F9C 55%,#FF9A6B 100%)}
.xj-empty__sun{position:absolute;right:100rpx;top:150rpx;width:136rpx;height:136rpx;border-radius:50%;background:#FFD2A8}
.xj-empty__m1{position:absolute;left:-60rpx;right:-60rpx;bottom:-140rpx;height:300rpx;background:#1E3A6E;opacity:.55;transform:rotate(-6deg);border-radius:50% 50% 0 0}
.xj-empty__m2{position:absolute;left:-40rpx;right:-120rpx;bottom:-180rpx;height:300rpx;background:#1E3A6E;opacity:.9;transform:rotate(5deg);border-radius:50% 50% 0 0}
.xj-empty__ht{position:absolute;left:36rpx;right:36rpx;top:36rpx;display:flex;flex-direction:column;color:#fff}
.xj-empty__k{font-size:var(--xj-font-mini);letter-spacing:4rpx;opacity:.9}
.xj-empty__title{font-size:var(--xj-font-h1);font-weight:700;margin-top:12rpx}
.xj-empty__sub{font-size:var(--xj-font-caption);opacity:.92;margin-top:8rpx}
.xj-empty__chips{display:flex;flex-wrap:wrap;gap:16rpx;margin-top:28rpx}
.xj-empty__chip{display:flex;align-items:center;gap:8rpx;height:68rpx;padding:0 24rpx;border-radius:var(--xj-radius-pill);background:var(--xj-card);border:2rpx solid var(--xj-line);font-size:var(--xj-font-sm);color:var(--xj-text);--xj-icon-size:26rpx}
.xj-empty__acts{margin-top:28rpx}''','''// 无行程状态（行程页即首页）：插画 hero + 快捷提示词。点提示词 → 填入 chat-bar 或直接发送
Component({
  properties: {
    kicker: { type: String, value: '行迹 · 你的旅行搭子' },
    title: { type: String, value: '想去哪儿？' },
    sub: { type: String, value: '一句话告诉我，Agent 帮你排好每一天' },
    prompts: { type: Array, value: ['北京 3 天，带爸妈不赶路', '周末杭州 citywalk', '粘贴小红书笔记导入'] }
  },
  methods: { onPrompt(e) { this.triggerEvent('prompt', { text: e.currentTarget.dataset.text }); } }
});''')

# chat-bar: add readonly/offline
# ---- app / demo ----
comps=['xj-nav-bar','xj-button','xj-chip','xj-score-chip','xj-quality-badge','xj-itinerary-card','xj-transit','xj-empty-slot','xj-alert-bar','xj-offline-bar','xj-chat-bar','xj-day-tabs','xj-bottom-sheet','xj-node-card','xj-toast','xj-conflict-preview','xj-skeleton','xj-trip-item','xj-import-result','xj-empty-state']
COMPS=comps
w('app.json',json.dumps({"pages":["pages/kit-demo/index","pages/kit-map/index"],"window":{"navigationBarTitleText":"行迹 UI Kit","navigationBarBackgroundColor":"#F7F5F0","navigationBarTextStyle":"black","backgroundColor":"#F7F5F0"},"style":"v2","sitemapLocation":"sitemap.json","lazyCodeLoading":"requiredComponents"},indent=2,ensure_ascii=False))
w('sitemap.json','{"rules":[{"action":"allow","page":"*"}]}')
w('app.js','App({});'); w('app.wxss','@import "styles/index.wxss";')
w('project.config.json',json.dumps({"appid":"touristappid","projectname":"xingji-ui-kit","compileType":"miniprogram","libVersion":"3.0.0","setting":{"es6":True,"enhance":True,"postcss":True,"minified":True},"condition":{}},indent=2))
uc={c:f"/components/{c}/index" for c in comps}
w('pages/kit-demo/index.json',json.dumps({"navigationBarTitleText":"行迹 UI Kit · 组件","usingComponents":uc},indent=2,ensure_ascii=False))
w('pages/kit-demo/index.wxml','''<view class="demo">
  <view class="sec"><view class="st">入口</view><xj-button type="dark" block bind:tap="goMap">打开行程页（首页）整页演示 ›</xj-button></view>
  <view class="sec"><view class="st">COLOR · 对比度</view><view class="sw"><view wx:for="{{colors}}" wx:key="name" class="sw__i"><view class="sw__c" style="background:{{item.hex}}"></view><text class="sw__n">{{item.name}}</text><text class="sw__h">{{item.hex}}</text></view></view></view>
  <view class="sec"><view class="st">BUTTON</view>
    <view class="row"><xj-button type="primary" icon="spark-white" bind:tap="onBtn">开始规划</xj-button><xj-button type="dark">保存行程</xj-button></view>
    <view class="row"><xj-button type="secondary">换一个</xj-button><xj-button type="text">查看全部 ›</xj-button></view>
    <view class="row"><xj-button type="primary" loading>规划中</xj-button><xj-button type="dark" disabled>不可用</xj-button><xj-button type="primary" size="sm">小号</xj-button></view>
  </view>
  <view class="sec"><view class="st">CHIP</view>
    <view class="row"><xj-chip wx:for="{{chips}}" wx:key="label" label="{{item.label}}" status="{{item.status}}" value="{{index}}" closable="{{item.closable}}" bind:tap="onChip" bind:close="onChipClose"></xj-chip></view>
  </view>
  <view class="sec"><view class="st">QUALITY BADGE（点击 → 透视面板） · SCORE（餐厅评分，中性）</view>
    <view class="row"><xj-quality-badge score="{{92}}" bind:tap="onQuality"></xj-quality-badge><xj-quality-badge score="{{78}}" bind:tap="onQuality"></xj-quality-badge><xj-quality-badge score="{{52}}" status="fail" bind:tap="onQuality"></xj-quality-badge></view>
    <view class="row"><xj-score-chip score="4.7"></xj-score-chip><xj-score-chip score="4.5" suffix="大众点评"></xj-score-chip></view>
  </view>
  <view class="sec"><view class="st">DAY TABS</view><xj-day-tabs days="{{days}}" current="{{day}}" bind:change="onDay"></xj-day-tabs></view>
  <view class="sec"><view class="st">ALERT · 单一提醒位（优先级 + 折叠）</view>
    <xj-alert-bar alerts="{{alerts}}" bind:action="onAlert"></xj-alert-bar><view class="gap"></view>
    <xj-alert-bar alerts="{{alerts2}}"></xj-alert-bar><view class="gap"></view>
    <xj-alert-bar type="info" text="Agent 已为你避开周末排队高峰" closable></xj-alert-bar><view class="gap"></view>
    <xj-offline-bar bind:retry="onAlert"></xj-offline-bar>
  </view>
  <view class="sec"><view class="st">ITINERARY CARD · TRANSIT · EMPTY SLOT</view>
    <xj-itinerary-card time="09:00" duration="2.5h" name="天坛公园" meta="祈年殿 · 回音壁 · 门票 ¥34" locked active item-id="1" bind:tap="onCard" bind:longpress="onCardLong"></xj-itinerary-card>
    <xj-transit mode="subway" text="地铁 5 号线 · 18 分钟"></xj-transit>
    <xj-empty-slot time="12:00" bind:tap="onSlot"></xj-empty-slot>
    <xj-transit mode="walk" text="步行 8 分钟" estimated></xj-transit>
    <xj-itinerary-card time="13:30" duration="1.5h" name="前门大街" meta="老字号 · 大栅栏" item-id="3"></xj-itinerary-card>
    <xj-transit mode="taxi" text="打车 12 分钟" estimated></xj-transit>
    <xj-itinerary-card time="15:30" duration="2h" name="国家博物馆" meta="需提前 3 天预约" conflict="仍然加入：当天结束时间晚于 21:00" item-id="4"></xj-itinerary-card>
    <view class="gap"></view>
    <xj-itinerary-card time="—" name="景山公园" meta="超出当天容量，已放入候补" waitlist item-id="5"></xj-itinerary-card>
    <view class="gap"></view>
    <xj-itinerary-card time="18:00" duration="1h" name="四季民福烤鸭" meta="人均 ¥180" rating="4.7" dimmed item-id="6"><view slot="tag" class="tag">已过时</view></xj-itinerary-card>
  </view>
  <view class="sec"><view class="st">NODE CARD（半屏）/ 玩法卡（全屏展开）</view>
    <xj-node-card index="1" name="天坛公园" time="09:00-11:30" duration="2.5h" meta="门票 ¥34" rating="4.8" locked tip="东门进，先祈年殿避开 10 点后旅行团" expanded="{{nodeExp}}" play-duration="2h" steps="{{steps}}" bind:expand="onExpand" bind:action="onNodeAct"></xj-node-card>
  </view>
  <view class="sec"><view class="st">CONFLICT PREVIEW（加点）</view>
    <xj-conflict-preview title="加入「景山公园」后" day-label="Day 1 结束" before="18:30" after="20:10" over impacts="{{impacts}}" bind:apply="onAlert" bind:force="onForce"></xj-conflict-preview>
  </view>
  <view class="sec"><view class="st">IMPORT RESULT（小红书）</view>
    <xj-import-result title="北京三日游｜不踩雷的中轴线路线" places="{{places}}" bind:confirm="onImport" bind:fix="onAlert" bind:origin="onOrigin"></xj-import-result>
  </view>
  <view class="sec"><view class="st">TRIP ITEM（我的行程）</view>
    <view wx:for="{{trips}}" wx:key="city" class="ti"><xj-trip-item city="{{item.city}}" dates="{{item.dates}}" days="{{item.days}}" status="{{item.status}}" summary="{{item.summary}}" cover="{{item.cover}}" trip-id="{{index}}" bind:tap="onTrip"></xj-trip-item></view>
  </view>
  <view class="sec"><view class="st">EMPTY STATE（无行程）</view><xj-empty-state bind:prompt="onPrompt"><xj-button type="primary" block icon="spark-white">开始规划</xj-button></xj-empty-state></view>
  <view class="sec"><view class="st">SKELETON</view><xj-skeleton type="card" rows="{{2}}"></xj-skeleton><xj-skeleton type="text" rows="{{3}}"></xj-skeleton></view>
  <view class="sec"><view class="st">CHAT BAR · TOAST</view>
    <xj-chat-bar bind:send="onSend"></xj-chat-bar><view class="gap"></view>
    <xj-chat-bar sending show-mic="{{false}}" placeholder="行迹思考中…"></xj-chat-bar><view class="gap"></view>
    <xj-chat-bar disabled placeholder="离线中，联网后可修改"></xj-chat-bar><view class="gap"></view>
    <xj-button type="secondary" bind:tap="showToast">触发 toast（5 秒 · 撤销）</xj-button>
    <text class="log" wx:if="{{log}}">事件：{{log}}</text>
  </view>
  <view class="sec"><view class="st">MAP MARKER</view><view class="row"><image wx:for="{{markerIcons}}" wx:key="*this" class="mk" src="/assets/markers/{{item}}.png"></image></view></view>
  <view style="height:120rpx"></view>
  <xj-toast id="toast" bottom="{{60}}" bind:action="onUndo"></xj-toast>
</view>''')
w('pages/kit-demo/index.wxss','''.demo{padding:24rpx 24rpx 0}
.sec{background:var(--xj-card);border-radius:var(--xj-radius-lg);padding:32rpx;margin-bottom:24rpx;box-shadow:var(--xj-shadow-card)}
.st{font-size:var(--xj-font-mini);font-weight:700;color:var(--xj-text3);letter-spacing:2rpx;margin-bottom:24rpx}
.row{display:flex;flex-wrap:wrap;gap:16rpx;align-items:center;margin-bottom:16rpx}
.sw{display:flex;flex-wrap:wrap;gap:16rpx}.sw__i{width:146rpx}.sw__c{height:88rpx;border-radius:var(--xj-radius-sm);border:2rpx solid rgba(0,0,0,.05)}
.sw__n{display:block;font-size:var(--xj-font-mini);margin-top:8rpx}.sw__h{font-size:20rpx;color:var(--xj-text3)}
.tag{font-size:20rpx;color:var(--xj-text2);background:var(--xj-bg);padding:2rpx 12rpx;border-radius:8rpx}
.gap{height:16rpx}.log{display:block;margin-top:16rpx;font-size:var(--xj-font-caption);color:var(--xj-text2)}
.mk{width:64rpx;height:64rpx}
.ti{margin-bottom:16rpx}''')
w('pages/kit-demo/index.js','''Page({
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
});''')
# full-page itinerary home demo
w('pages/kit-map/index.json',json.dumps({"navigationStyle":"custom","usingComponents":uc},indent=2,ensure_ascii=False))
w('pages/kit-map/index.wxml','''<view class="page">
  <map class="map" latitude="39.892" longitude="116.402" scale="13" markers="{{markers}}" polyline="{{polyline}}" bindmarkertap="onMarker"></map>
  <xj-nav-bar title="北京 3 日游" subtitle="10/24 - 10/26" bind:left="onMyTrips" bind:ready="onNavReady"></xj-nav-bar>
  <view class="overlay" style="top:{{navH + 8}}px">
    <xj-quality-badge score="{{score}}" bind:tap="openInsight"></xj-quality-badge>
  </view>
  <xj-bottom-sheet level="{{level}}" top-offset="{{navH}}" bind:change="onLevel">
    <view slot="header">
      <xj-day-tabs days="{{days}}" current="{{day}}" bind:change="onDay"></xj-day-tabs>
      <view style="height:16rpx"></view>
      <xj-offline-bar wx:if="{{offline}}"></xj-offline-bar>
      <xj-alert-bar wx:else alerts="{{alerts}}"></xj-alert-bar>
    </view>
    <block wx:if="{{focus}}">
      <xj-node-card index="1" name="天坛公园" time="09:00-11:30" duration="2.5h" meta="门票 ¥34" rating="4.8" locked tip="东门进，先祈年殿避开旅行团" expanded="{{level==='full'}}" play-duration="2h" steps="{{steps}}" bind:expand="onExpand" bind:close="onCloseNode" bind:action="onNodeAct"></xj-node-card>
    </block>
    <block wx:else>
      <xj-itinerary-card time="09:00" duration="2.5h" name="天坛公园" meta="祈年殿 · 门票 ¥34" locked item-id="1" bind:tap="onCard"></xj-itinerary-card>
      <xj-transit mode="subway" text="地铁 18 分钟"></xj-transit>
      <xj-empty-slot time="12:00"></xj-empty-slot>
      <xj-transit mode="walk" text="步行 8 分钟" estimated></xj-transit>
      <xj-itinerary-card time="13:30" duration="1.5h" name="前门大街" meta="老字号 · 大栅栏" item-id="3" bind:tap="onCard"></xj-itinerary-card>
      <xj-transit mode="taxi" text="打车 15 分钟"></xj-transit>
      <xj-itinerary-card time="15:30" duration="2h" name="国家博物馆" meta="需预约" item-id="4" bind:tap="onCard"></xj-itinerary-card>
    </block>
  </xj-bottom-sheet>
  <view class="chat"><xj-chat-bar disabled="{{offline}}" placeholder="{{offline?'离线中，联网后可修改':'告诉行迹：下午想轻松点…'}}" bind:send="onSend"></xj-chat-bar></view>
  <xj-toast id="toast"></xj-toast>
  <view class="sw" bindtap="toggleOffline">{{offline?'在线':'离线'}}演示</view>
</view>''')
w('pages/kit-map/index.wxss','''.page{height:100vh;overflow:hidden}
.map{position:fixed;top:0;left:0;width:100%;height:100vh}
.overlay{position:fixed;left:24rpx;z-index:var(--xj-z-map-overlay)}
.chat{position:fixed;left:24rpx;right:24rpx;bottom:calc(24rpx + env(safe-area-inset-bottom));z-index:var(--xj-z-chat)}
.sw{position:fixed;right:24rpx;top:50%;z-index:var(--xj-z-map-overlay);font-size:22rpx;padding:8rpx 16rpx;background:var(--xj-card);border-radius:var(--xj-radius-pill);color:var(--xj-text2)}''')
w('pages/kit-map/index.js','''const { poiMarker, typeMarker, routeLine } = require('../../utils/map-style.js');
const pts = [
  { latitude: 39.8822, longitude: 116.4066 }, { latitude: 39.8930, longitude: 116.3990 },
  { latitude: 39.8970, longitude: 116.3980 }, { latitude: 39.9050, longitude: 116.4010 }
];
Page({
  data: {
    navH: 64, level: 'half', day: 0, score: 78, focus: false, offline: false,
    days: [{ label: 'Day 1', sub: '周六', today: true }, { label: 'Day 2', sub: '周日', warn: true }, { label: 'Day 3', sub: '周一' }],
    alerts: [{ id: 'q', type: 'quality', text: '评审 78：午餐未定、Day2 步行偏多', actionText: '看透视' }, { id: 'r', type: 'risk', text: '周日下午雷阵雨' }],
    steps: [{ title: '东门进 · 祈年殿', time: '40min' }, { title: '回音壁', time: '30min' }, { title: '圜丘坛', time: '20min' }],
    markers: [
      poiMarker(1, pts[0].latitude, pts[0].longitude, 1), typeMarker(2, pts[1].latitude, pts[1].longitude, 'restaurant-orange'),
      poiMarker(3, pts[2].latitude, pts[2].longitude, 3), poiMarker(4, pts[3].latitude, pts[3].longitude, 4),
      typeMarker(9, 39.8800, 116.4150, 'current')
    ],
    polyline: [routeLine(pts, 'current')]
  },
  onNavReady(e) { this.setData({ navH: e.detail.totalHeight }); },
  onMyTrips() { wx.showToast({ title: '→ 我的行程', icon: 'none' }); },
  openInsight() { wx.showToast({ title: '打开 Agent 透视面板', icon: 'none' }); },
  onLevel(e) { this.setData({ level: e.detail.level }); },
  onDay(e) { this.setData({ day: e.detail.index }); },
  onMarker() { this.setData({ focus: true, level: 'half' }); },
  onCard() { this.setData({ focus: true, level: 'half' }); },
  onExpand(e) { this.setData({ level: e.detail.expanded ? 'full' : 'half' }); },
  onCloseNode() { this.setData({ focus: false }); },
  onNodeAct(e) { if (e.detail.act === 'delete') { this.setData({ focus: false }); this.selectComponent('#toast').show({ text: '已删除 天坛公园' }); } },
  onSend(e) { this.selectComponent('#toast').show({ text: '已调整：下午改为前门大街慢逛' }); },
  toggleOffline() { this.setData({ offline: !this.data.offline }); }
});''')
