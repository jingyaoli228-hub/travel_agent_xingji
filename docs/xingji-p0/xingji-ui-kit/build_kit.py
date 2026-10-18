import os,json,urllib.parse
R='/workspace/xingji-visual/kit'
def w(p,s):
    p=os.path.join(R,p);os.makedirs(os.path.dirname(p),exist_ok=True);open(p,'w').write(s.strip()+'\n')
C=dict(primary='#1E3A6E',primary2='#2F5597',primaryLight='#E6ECF6',accent='#FF7A45',accentLight='#FFEDE4',cta='#C2410C',ctaPressed='#9A3412',ctaLight='#FDEBE1',bg='#F7F5F0',card='#FFFFFF',text='#1B2333',text2='#5F6878',text3='#666E7D',textDisabled='#9AA1AD',line='#E8E4DC',success='#1F7A52',successIcon='#2E9E6B',successLight='#E3F4EC',warn='#E8A317',warnLight='#FFF5DC',warnText='#7A5200',error='#B42318',errorLight='#FDECEC',info='#2F5597',infoLight='#E6ECF6',exclude='#F4F4F4')
def kb(s): import re;return re.sub(r'([A-Z])',lambda m:'-'+m.group(1).lower(),s)
tok='\n'.join(f'  --xj-{kb(k)}: {v};' for k,v in C.items())
w('styles/tokens.wxss',f'''/* 行迹 UI Kit · Direction A 藏青+暖橙 · design width 750rpx (1px = 2rpx) */
page {{
  /* color */
{tok}
  /* radius */
  --xj-radius-xs: 8rpx; --xj-radius-sm: 16rpx; --xj-radius-md: 24rpx; --xj-radius-lg: 32rpx; --xj-radius-xl: 44rpx; --xj-radius-pill: 999rpx;
  /* spacing (8rpx grid) */
  --xj-space-1: 8rpx; --xj-space-2: 16rpx; --xj-space-3: 24rpx; --xj-space-4: 32rpx; --xj-space-5: 40rpx; --xj-space-6: 48rpx;
  /* font size */
  --xj-font-h1: 48rpx; --xj-font-h2: 36rpx; --xj-font-h3: 32rpx; --xj-font-body: 30rpx; --xj-font-sm: 26rpx; --xj-font-caption: 24rpx; --xj-font-mini: 22rpx; --xj-font-num: 40rpx;
  --xj-weight-regular: 400; --xj-weight-medium: 500; --xj-weight-bold: 700;
  --xj-font-family: -apple-system, "PingFang SC", "Noto Sans CJK SC", "Helvetica Neue", sans-serif;
  /* shadow */
  --xj-shadow-card: 0 2rpx 4rpx rgba(20,30,50,0.04), 0 12rpx 40rpx rgba(20,30,50,0.05);
  --xj-shadow-float: 0 12rpx 40rpx rgba(20,30,50,0.10);
  --xj-shadow-tab: 0 16rpx 48rpx rgba(20,30,50,0.12);
  --xj-shadow-cta: 0 8rpx 24rpx rgba(194,65,12,0.28);
  --xj-shadow-primary: 0 12rpx 32rpx rgba(30,58,110,0.40);
  /* z-index */
  --xj-z-map-overlay: 10; --xj-z-sheet: 20; --xj-z-chat: 30; --xj-z-nav: 40; --xj-z-popup: 100; --xj-z-toast: 1000;
  /* size */
  --xj-btn-h: 88rpx; --xj-btn-h-sm: 64rpx; --xj-chip-h: 64rpx; --xj-nav-h: 88rpx; --xj-sheet-peek: 300rpx; --xj-chat-h: 100rpx;
  background: var(--xj-bg); color: var(--xj-text); font-family: var(--xj-font-family);
}}''')
# icons
P={'lock':'<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>','star':'<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>',
'mic':'<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>','send':'<path d="M4 12l16-8-6 16-3-7z"/>','spark':'<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6"/>',
'walk':'<circle cx="13" cy="4" r="2"/><path d="M10 21l2-7 3 3v5M8 12l3-4 4 2 2 3"/>','subway':'<rect x="6" y="3" width="12" height="14" rx="3"/><path d="M6 11h12M9 21l1-4M15 21l-1-4"/>','bus':'<rect x="4" y="4" width="16" height="13" rx="2"/><path d="M4 11h16M7 21v-4M17 21v-4"/>','taxi':'<path d="M5 16V11l2-5h10l2 5v5zM3 16h18v3H3zM9 3h6"/>','bike':'<circle cx="6" cy="16" r="3.5"/><circle cx="18" cy="16" r="3.5"/><path d="M6 16l4-8h5l3 8M10 8l2 8"/>',
'warn':'<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v.5"/>','info':'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>','error':'<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>','close':'<path d="M6 6l12 12M18 6L6 18"/>',
'map':'<path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2z"/><path d="M9 4v14M15 6v14"/>','trip':'<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v4M16 3v4M4 10h16"/>','me':'<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4-6 8-6s7 2 8 6"/>','check':'<path d="M5 12l5 5 9-10"/>','list':'<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>','chevron':'<path d="M9 5l7 7-7 7"/>','up':'<path d="M6 15l6-6 6 6"/>','undo':'<path d="M9 14L4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>','offline':'<path d="M2 8.5a15 15 0 0 1 5-3M22 8.5a15 15 0 0 0-11-3.8M5 12.5a10 10 0 0 1 3-2M19 12.5a10 10 0 0 0-4-2.3M8.5 16a5 5 0 0 1 7 0M12 20h.01M3 3l18 18"/>','clock':'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>','link':'<path d="M10 14a4 4 0 0 0 6 0l3-3a4 4 0 0 0-6-6l-1 1M14 10a4 4 0 0 0-6 0l-3 3a4 4 0 0 0 6 6l1-1"/>','shield':'<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>','drag':'<path d="M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01"/>','trash':'<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>','refresh':'<path d="M20 11a8 8 0 0 0-14.5-4.5L4 8M4 4v4h4M4 13a8 8 0 0 0 14.5 4.5L20 16M20 20v-4h-4"/>'}
COLS={'navy':C['primary'],'orange':C['accent'],'grey':C['text3'],'white':'#FFFFFF','green':C['success'],'amber':C['warn'],'red':C['error'],'blue':C['info'],'dark':C['text2']}
def uri(d,c): s=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{d}</svg>';return 'data:image/svg+xml;charset=utf-8,'+urllib.parse.quote(s)
css=['/* 自绘线性图标：<view class="xj-icon xj-icon--lock-navy"></view>，尺寸用 --xj-icon-size 或覆写 width/height */',
'.xj-icon{display:inline-block;width:var(--xj-icon-size,36rpx);height:var(--xj-icon-size,36rpx);background-size:100% 100%;background-repeat:no-repeat;flex-shrink:0;vertical-align:middle}']
for n,d in P.items():
    for cn,cv in COLS.items(): css.append(f'.xj-icon--{n}-{cn}{{background-image:url("{uri(d,cv)}")}}')
w('styles/icons.wxss','\n'.join(css))
os.makedirs(R+'/assets/icons/svg',exist_ok=True)
for n,d in P.items(): open(f'{R}/assets/icons/svg/{n}.svg','w').write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{C["primary"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{d}</svg>')
w('styles/index.wxss','@import "./tokens.wxss";\n@import "./icons.wxss";')

def comp(name,wxml,wxss,js):
    w(f'components/{name}/index.wxml',wxml);w(f'components/{name}/index.wxss',wxss);w(f'components/{name}/index.js',js)
    w(f'components/{name}/index.json',json.dumps({"component":True,"styleIsolation":"apply-shared","usingComponents":{}},indent=2))
comp('xj-button','''<button class="xj-btn xj-btn--{{type}} xj-btn--{{size}} {{block?'xj-btn--block':''}} {{disabled?'is-disabled':''}}" hover-class="{{disabled||loading?'none':'xj-btn--hover'}}" disabled="{{disabled}}" open-type="{{openType}}" bindtap="onTap">
  <view wx:if="{{loading}}" class="xj-btn__spin"></view>
  <view wx:elif="{{icon}}" class="xj-icon xj-icon--{{icon}} xj-btn__icon"></view>
  <slot></slot>
</button>''','''.xj-btn{display:inline-flex;align-items:center;justify-content:center;gap:12rpx;height:var(--xj-btn-h);padding:0 44rpx;margin:0;border-radius:var(--xj-radius-pill);font-size:var(--xj-font-body);font-weight:var(--xj-weight-bold);line-height:1;border:none;box-sizing:border-box}
.xj-btn::after{border:none}
.xj-btn--sm{height:var(--xj-btn-h-sm);padding:0 28rpx;font-size:var(--xj-font-sm)}
.xj-btn--block{display:flex;width:100%}
.xj-btn--primary{background:var(--xj-cta);color:#fff;box-shadow:var(--xj-shadow-cta)}
.xj-btn--primary.xj-btn--hover{background:var(--xj-cta-pressed);opacity:1}
.xj-btn--dark{background:var(--xj-primary);color:#fff}
.xj-btn--secondary{background:var(--xj-primary-light);color:var(--xj-primary)}
.xj-btn--text{background:transparent;color:var(--xj-primary);padding:0 16rpx}
.xj-btn--hover{opacity:.85}
.xj-btn.is-disabled{background:var(--xj-line)!important;color:var(--xj-text3)!important;box-shadow:none!important}
.xj-btn--text.is-disabled{background:transparent!important}
.xj-btn__icon{--xj-icon-size:32rpx}
.xj-btn__spin{width:32rpx;height:32rpx;border-radius:50%;border:4rpx solid currentColor;border-right-color:transparent;animation:xjspin .8s linear infinite}
@keyframes xjspin{to{transform:rotate(360deg)}}''','''Component({
  options: { multipleSlots: true },
  properties: {
    type: { type: String, value: 'primary' }, // primary | dark | secondary | text
    size: { type: String, value: 'md' },      // md | sm
    block: { type: Boolean, value: false },
    loading: { type: Boolean, value: false },
    disabled: { type: Boolean, value: false },
    icon: { type: String, value: '' },        // icons.wxss 名，如 'spark-white'
    openType: { type: String, value: '' }
  },
  methods: {
    onTap() {
      if (this.data.disabled || this.data.loading) return;
      this.triggerEvent('tap', {});
    }
  }
});''')
comp('xj-chip','''<view class="xj-chip xj-chip--{{status}} xj-chip--{{size}}" hover-class="xj-chip--hover" bindtap="onTap">
  <view wx:if="{{status==='selected'}}" class="xj-icon xj-icon--check-white xj-chip__pre"></view>
  <view wx:elif="{{status==='must'}}" class="xj-icon xj-icon--star-green xj-chip__pre"></view>
  <text class="xj-chip__label">{{label}}</text><slot></slot>
  <view wx:if="{{closable}}" class="xj-chip__close" catchtap="onClose"><view class="xj-icon xj-icon--close-{{status==='selected'?'white':'grey'}}"></view></view>
</view>''','''.xj-chip{display:inline-flex;align-items:center;gap:8rpx;height:var(--xj-chip-h);padding:0 28rpx;border-radius:var(--xj-radius-pill);font-size:var(--xj-font-sm);border:2rpx solid var(--xj-line);background:var(--xj-card);color:var(--xj-text2);box-sizing:border-box;white-space:nowrap}
.xj-chip--sm{height:52rpx;padding:0 20rpx;font-size:var(--xj-font-caption)}
.xj-chip--selected{background:var(--xj-primary);border-color:var(--xj-primary);color:#fff}
.xj-chip--must{background:var(--xj-success-light);border-color:transparent;color:var(--xj-success)}
.xj-chip--exclude{background:var(--xj-exclude);border-color:transparent;color:var(--xj-text3)}
.xj-chip--exclude .xj-chip__label{text-decoration:line-through}
.xj-chip--hover{opacity:.8}
.xj-chip__pre{--xj-icon-size:26rpx}
.xj-chip__close{margin-right:-8rpx;padding:4rpx;--xj-icon-size:24rpx;display:flex}''','''Component({
  properties: {
    label: { type: String, value: '' },
    status: { type: String, value: 'default' }, // default | selected | must | exclude
    size: { type: String, value: 'md' },        // md | sm
    closable: { type: Boolean, value: false },
    value: { type: null, value: null }
  },
  methods: {
    onTap() { this.triggerEvent('tap', { value: this.data.value, status: this.data.status }); },
    onClose() { this.triggerEvent('close', { value: this.data.value }); }
  }
});''')
comp('xj-score-chip','<view class="xj-score" bindtap="onTap"><view class="xj-icon xj-icon--star-dark"></view><text class="xj-score__num">{{score}}</text><text wx:if="{{suffix}}" class="xj-score__suf">{{suffix}}</text></view>',
'''.xj-score{display:inline-flex;align-items:center;gap:6rpx;height:40rpx;padding:0 14rpx;border-radius:var(--xj-radius-pill);font-size:var(--xj-font-mini);background:var(--xj-bg);color:var(--xj-text2);border:2rpx solid var(--xj-line);box-sizing:border-box;--xj-icon-size:22rpx;white-space:nowrap}
.xj-score__num{font-weight:var(--xj-weight-bold);color:var(--xj-text)}.xj-score__suf{color:var(--xj-text3)}''','''// 仅用于餐厅/POI 第三方评分（中性灰，不用橙色）。行程质量请用 xj-quality-badge
Component({
  properties: {
    score: { type: null, value: '' },   // 4.7
    suffix: { type: String, value: '' } // 如 '大众点评'
  },
  methods: { onTap() { this.triggerEvent('tap', { score: this.data.score }); } }
});''')
comp('xj-itinerary-card','''<view class="xj-card {{active?'is-active':''}} {{dimmed?'is-dimmed':''}} {{waitlist?'is-wait':''}} {{conflict?'is-conflict':''}}" hover-class="xj-card--hover" bindtap="onTap" bindlongpress="onLongPress">
  <view class="xj-card__time"><text class="xj-card__t">{{time}}</text><text wx:if="{{duration}}" class="xj-card__d">{{duration}}</text></view>
  <view class="xj-card__body">
    <view class="xj-card__head">
      <text class="xj-card__name">{{name}}</text>
      <view wx:if="{{locked}}" class="xj-card__lock"><view class="xj-icon xj-icon--lock-green"></view>已锁定</view>
      <view wx:if="{{waitlist}}" class="xj-card__wait">候补</view>
      <xj-score-chip wx:if="{{rating}}" score="{{rating}}"></xj-score-chip>
      <slot name="tag"></slot>
    </view>
    <text wx:if="{{meta}}" class="xj-card__meta">{{meta}}</text>
    <view wx:if="{{conflict}}" class="xj-card__cf"><view class="xj-icon xj-icon--warn-red"></view>{{conflict}}</view>
    <slot></slot>
  </view>
  <slot name="right"></slot>
</view>''','''.xj-card{display:flex;gap:24rpx;padding:28rpx;border-radius:var(--xj-radius-md);background:var(--xj-card);border:2rpx solid var(--xj-line);box-sizing:border-box}
.xj-card--hover{background:#FBFAF7}
.xj-card.is-active{border-color:var(--xj-accent);box-shadow:0 0 0 4rpx var(--xj-accent-light)}
.xj-card.is-dimmed{opacity:.55}
.xj-card.is-wait{border-style:dashed;background:#FBFAF7}.xj-card.is-wait .xj-card__name{color:var(--xj-text2)}
.xj-card.is-conflict{border-color:var(--xj-error);box-shadow:0 0 0 4rpx var(--xj-error-light)}
.xj-card__wait{height:40rpx;line-height:36rpx;padding:0 14rpx;border-radius:var(--xj-radius-pill);border:2rpx dashed var(--xj-text3);color:var(--xj-text3);font-size:var(--xj-font-mini);box-sizing:border-box}
.xj-card__cf{display:flex;align-items:center;gap:8rpx;margin-top:10rpx;font-size:var(--xj-font-caption);color:var(--xj-error);--xj-icon-size:26rpx}
.xj-card__time{width:88rpx;flex-shrink:0;display:flex;flex-direction:column;padding-top:4rpx}
.xj-card__t{font-size:var(--xj-font-sm);font-weight:700;color:var(--xj-primary)}
.xj-card__d{font-size:var(--xj-font-mini);color:var(--xj-text3);margin-top:4rpx}
.xj-card__body{flex:1;min-width:0}
.xj-card__head{display:flex;align-items:center;gap:12rpx;flex-wrap:wrap}
.xj-card__name{font-size:var(--xj-font-body);font-weight:700;color:var(--xj-text)}
.xj-card__lock{display:inline-flex;align-items:center;gap:6rpx;height:40rpx;padding:0 16rpx;border-radius:var(--xj-radius-pill);background:var(--xj-success-light);color:var(--xj-success);font-size:var(--xj-font-mini);--xj-icon-size:22rpx}
.xj-card__meta{display:block;margin-top:8rpx;font-size:var(--xj-font-caption);color:var(--xj-text2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}''','''Component({
  options: { multipleSlots: true },
  properties: {
    time: { type: String, value: '' },      // '09:00'
    duration: { type: String, value: '' },  // '2.5h'
    name: { type: String, value: '' },
    meta: { type: String, value: '' },
    locked: { type: Boolean, value: false },
    rating: { type: null, value: '' },      // 4.7，空则不显示
    active: { type: Boolean, value: false },// 与地图当前选中点联动
    dimmed: { type: Boolean, value: false },
    waitlist: { type: Boolean, value: false }, // 候补：超出容量自动放入，虚线 + 「候补」
    conflict: { type: String, value: '' },     // 「仍然加入」后的冲突原因，非空则红框并显示
    itemId: { type: null, value: null }
  },
  methods: {
    onTap() { this.triggerEvent('tap', { id: this.data.itemId }); },
    onLongPress() { this.triggerEvent('longpress', { id: this.data.itemId }); }
  }
});''')
w('components/xj-itinerary-card/index.json',json.dumps({"component":True,"styleIsolation":"apply-shared","usingComponents":{"xj-score-chip":"../xj-score-chip/index"}},indent=2))
comp('xj-transit','''<view class="xj-transit {{estimated?'is-est':''}}" bindtap="onTap"><view class="xj-transit__line"></view><view class="xj-icon xj-icon--{{mode}}-grey"></view><text wx:if="{{estimated}}" class="xj-transit__est">≈</text><text>{{text}}</text><text wx:if="{{estimated}}" class="xj-transit__tag">估算</text><slot></slot></view>''',
'''.xj-transit{display:flex;align-items:center;gap:10rpx;padding:8rpx 0 8rpx 40rpx;font-size:var(--xj-font-mini);color:var(--xj-text3);--xj-icon-size:26rpx}
.xj-transit.is-est .xj-transit__line{background:repeating-linear-gradient(var(--xj-text-disabled) 0 4rpx,transparent 4rpx 12rpx)}
.xj-transit__est{font-weight:700;color:var(--xj-text2)}.xj-transit__tag{margin-left:4rpx;padding:0 10rpx;border:2rpx dashed var(--xj-text-disabled);border-radius:var(--xj-radius-xs);font-size:20rpx;line-height:30rpx}
.xj-transit__line{width:4rpx;height:40rpx;margin-right:28rpx;background:repeating-linear-gradient(var(--xj-line) 0 8rpx,transparent 8rpx 14rpx)}''','''Component({
  properties: {
    mode: { type: String, value: 'walk' }, // walk | subway | bus | taxi | bike
    text: { type: String, value: '' },     // '地铁 5 号线 · 18 分钟'
    estimated: { type: Boolean, value: false } // 估算段：前缀 ≈、虚线更稀、带「估算」标
  },
  methods: { onTap() { this.triggerEvent('tap', { mode: this.data.mode, estimated: this.data.estimated }); } }
});''')
comp('xj-chat-bar','''<view class="xj-chat {{fixed?'xj-chat--fixed':''}}" style="{{fixed?'bottom:'+bottom+'rpx':''}}">
  <view class="xj-icon xj-icon--spark-navy"></view>
  <input class="xj-chat__input" value="{{value}}" placeholder="{{placeholder}}" placeholder-class="xj-chat__ph" confirm-type="send" disabled="{{disabled}}" adjust-position="{{true}}" bindinput="onInput" bindconfirm="onSend" bindfocus="onFocus" bindblur="onBlur"/>
  <view wx:if="{{showMic}}" class="xj-chat__mic" bindtouchstart="onMicStart" bindtouchend="onMicEnd"><view class="xj-icon xj-icon--mic-{{recording?'orange':'grey'}}"></view></view>
  <view class="xj-chat__send {{value&&!sending?'':'is-off'}}" bindtap="onSend">
    <view wx:if="{{sending}}" class="xj-chat__spin"></view><view wx:else class="xj-icon xj-icon--send-white"></view>
  </view>
</view>''','''.xj-chat{display:flex;align-items:center;gap:16rpx;height:var(--xj-chat-h);padding:0 12rpx 0 32rpx;background:var(--xj-card);border-radius:var(--xj-radius-pill);border:2rpx solid var(--xj-line);box-shadow:var(--xj-shadow-float);box-sizing:border-box}
.xj-chat--fixed{position:fixed;left:24rpx;right:24rpx;z-index:var(--xj-z-chat)}
.xj-chat__input{flex:1;height:100%;font-size:var(--xj-font-sm);color:var(--xj-text)}
.xj-chat__ph{color:var(--xj-text3)}
.xj-chat__mic{padding:8rpx;display:flex}
.xj-chat__send{width:76rpx;height:76rpx;border-radius:50%;background:var(--xj-primary);display:flex;align-items:center;justify-content:center;--xj-icon-size:32rpx}
.xj-chat__send.is-off{opacity:.4}
.xj-chat__spin{width:30rpx;height:30rpx;border-radius:50%;border:4rpx solid #fff;border-right-color:transparent;animation:xjspin2 .8s linear infinite}
@keyframes xjspin2{to{transform:rotate(360deg)}}''','''Component({
  properties: {
    placeholder: { type: String, value: '告诉行迹：下午想轻松点…' },
    showMic: { type: Boolean, value: true },
    sending: { type: Boolean, value: false },
    disabled: { type: Boolean, value: false },
    fixed: { type: Boolean, value: false },   // 固定在底部
    bottom: { type: Number, value: 44 },      // fixed 时距底 rpx（有 tabBar 时传 160）
    clearOnSend: { type: Boolean, value: true }
  },
  data: { value: '', recording: false },
  methods: {
    onInput(e) { this.setData({ value: e.detail.value }); this.triggerEvent('input', { value: e.detail.value }); },
    onSend() {
      const value = (this.data.value || '').trim();
      if (!value || this.data.sending) return;
      this.triggerEvent('send', { value });
      if (this.data.clearOnSend) this.setData({ value: '' });
    },
    onFocus(e) { this.triggerEvent('focus', e.detail); },
    onBlur(e) { this.triggerEvent('blur', e.detail); },
    onMicStart() { this.setData({ recording: true }); this.triggerEvent('micstart', {}); },
    onMicEnd() { this.setData({ recording: false }); this.triggerEvent('micend', {}); },
    setValue(v) { this.setData({ value: v || '' }); }
  }
});''')
comp('xj-day-tabs','''<scroll-view class="xj-days" scroll-x enhanced show-scrollbar="{{false}}"><view class="xj-days__in">
  <view wx:for="{{days}}" wx:key="index" class="xj-days__item {{index===current?'is-on':''}}" data-index="{{index}}" bindtap="onTap">
    <text class="xj-days__l">{{item.label}}</text><text wx:if="{{item.today}}" class="xj-days__today">今天</text><text wx:if="{{item.sub}}" class="xj-days__s"> · {{item.sub}}</text>
    <view wx:if="{{item.warn}}" class="xj-days__dot"></view>
  </view>
</view></scroll-view>''','''.xj-days{width:100%;white-space:nowrap}
.xj-days__in{display:inline-flex;gap:16rpx;padding:4rpx 0}
.xj-days__item{position:relative;display:inline-flex;align-items:center;height:60rpx;padding:0 28rpx;border-radius:var(--xj-radius-pill);background:var(--xj-card);border:2rpx solid var(--xj-line);font-size:var(--xj-font-caption);color:var(--xj-text2);box-sizing:border-box}
.xj-days__item.is-on{background:var(--xj-primary);border-color:var(--xj-primary);color:#fff;font-weight:700}
.xj-days__today{margin-left:8rpx;padding:0 8rpx;border-radius:8rpx;background:var(--xj-success-light);color:var(--xj-success);font-size:20rpx}
.xj-days__s{font-weight:400}
.xj-days__dot{position:absolute;top:4rpx;right:8rpx;width:14rpx;height:14rpx;border-radius:50%;background:var(--xj-warn);border:2rpx solid #fff}''','''Component({
  properties: {
    days: { type: Array, value: [] },    // [{ label:'Day 1', sub:'周六', warn:false, today:false }]
    current: { type: Number, value: 0 }
  },
  methods: {
    onTap(e) {
      const index = Number(e.currentTarget.dataset.index);
      if (index === this.data.current) return;
      this.setData({ current: index });
      this.triggerEvent('change', { index });
    }
  }
});''')
w('utils/map-style.js',f'''/* 行迹 · <map> 组件样式常量（微信原生 map，腾讯底图；高德 SDK 仅取数据时同样适用） */
const COLOR = {{ primary: '{C['primary']}', accent: '{C['accent']}', other: '#1E3A6E59', white: '#FFFFFF' }};
const MARKER_SIZE = {{ width: 32, height: 32 }}; // px，图片为 64x64 @2x
const ICON_DIR = '/assets/markers/';
// 当天（选中天）路线：唯一使用暖橙
const POLYLINE_CURRENT = {{ color: '#FF7A45FF', width: 6, borderColor: '#FFFFFFFF', borderWidth: 2, arrowLine: true, level: 'abovelabels' }};
// 其他天：藏青 35% 虚线
const POLYLINE_OTHER = {{ color: '#1E3A6E59', width: 4, dottedLine: true, level: 'abovelabels' }};
// 步行接驳段
const POLYLINE_WALK = {{ color: '#FF7A45B3', width: 4, dottedLine: true, level: 'abovelabels' }};

function poiMarker(id, latitude, longitude, index, opts = {{}}) {{
  const current = opts.current !== false; // 属于当天 → 橙色，否则藏青
  const n = Math.min(Math.max(index, 1), 20);
  return Object.assign({{
    id, latitude, longitude,
    iconPath: `${{ICON_DIR}}poi-${{current ? 'orange' : 'navy'}}-${{n}}.png`,
    width: MARKER_SIZE.width, height: MARKER_SIZE.height,
    anchor: {{ x: 0.5, y: 0.5 }}, zIndex: current ? 20 : 10
  }}, opts.extra || {{}});
}}
function typeMarker(id, latitude, longitude, type, extra = {{}}) {{
  // type: restaurant | restaurant-orange | hotel | current
  const size = type === 'current' ? {{ width: 36, height: 36 }} : MARKER_SIZE;
  return Object.assign({{ id, latitude, longitude, iconPath: `${{ICON_DIR}}${{type}}.png`, anchor: {{ x: 0.5, y: 0.5 }}, zIndex: type === 'current' ? 30 : 15 }}, size, extra);
}}
function routeLine(points, kind = 'current') {{
  const base = kind === 'current' ? POLYLINE_CURRENT : kind === 'walk' ? POLYLINE_WALK : POLYLINE_OTHER;
  return Object.assign({{ points }}, base);
}}
module.exports = {{ COLOR, MARKER_SIZE, ICON_DIR, POLYLINE_CURRENT, POLYLINE_OTHER, POLYLINE_WALK, poiMarker, typeMarker, routeLine }};''')
# demo app
w('app.json',json.dumps({"pages":["pages/kit-demo/index"],"window":{"navigationBarTitleText":"行迹 UI Kit","navigationBarBackgroundColor":"#F7F5F0","navigationBarTextStyle":"black","backgroundColor":"#F7F5F0"},"style":"v2","sitemapLocation":"sitemap.json","lazyCodeLoading":"requiredComponents"},indent=2,ensure_ascii=False))
w('sitemap.json','{"rules":[{"action":"allow","page":"*"}]}')
w('app.js','App({});'); w('app.wxss','@import "styles/index.wxss";')
w('project.config.json',json.dumps({"appid":"touristappid","projectname":"xingji-ui-kit","compileType":"miniprogram","libVersion":"3.0.0","setting":{"es6":True,"enhance":True,"postcss":True,"minified":True},"condition":{}},indent=2))
exec(open('/workspace/xingji-visual/build_v2.py').read())
