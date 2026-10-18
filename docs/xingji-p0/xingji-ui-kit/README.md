# 行迹 UI 组件包 · 视觉规范与接入文档（A 藏青 + 暖橙）· v2

> 原生微信小程序**视觉组件包**（不含业务逻辑）。设计宽 **750rpx**，所有尺寸以 rpx 书写（设计稿 1px = 2rpx）。基础库 ≥ 2.20（推荐 3.x），WebView 渲染。
> v2 依据 UX 评审（`xingji-handoff/UX_review_v1.md`）修订：**行程页即首页**、去掉 tabBar、单一提醒位、透视开关改为点评审徽标、对比度达标、补齐 P0 组件。

---

## 0. v2 变更摘要

| 变更 | 说明 |
|---|---|
| 删除 `xj-tab-bar` | 行程页做首页，左上角「我的行程」进入列表；无收藏/住宿/门票/美食入口 |
| 新增 `xj-nav-bar` | 自定义导航栏，按胶囊位置对齐，右侧胶囊区不放东西 |
| 首页 hero / 快捷入口 → `xj-empty-state` | 仅在「无行程」时出现：插画 + 快捷提示词 |
| 删除常驻「Agent 透视」开关 | 改为点 `xj-quality-badge` 打开透视面板 |
| 新增 `xj-quality-badge` | 行程质量：pass ≥85 / draft <85（显示「草稿」）/ fail |
| `xj-score-chip` 改中性灰 | 只用于餐厅/POI 第三方评分，不再用橙色 |
| 对比度 | 主按钮改 **CTA 橙 #C2410C**（白字 5.18:1）；#FF7A45 只用于地图图形；三级文字改 #666E7D |
| `xj-alert-bar` 单一提醒位 | 传 `alerts` 数组，按优先级显示一条，其余折叠为「N 条提醒」 |
| P0 新组件 | xj-bottom-sheet、xj-node-card（含玩法卡展开）、xj-toast（撤销）、xj-conflict-preview、xj-offline-bar、xj-skeleton、xj-empty-slot、xj-trip-item、xj-import-result |
| 既有组件增强 | xj-transit `estimated`（≈ + 虚线）、xj-itinerary-card `waitlist`（候补）/`conflict`（仍然加入后标红）、xj-day-tabs `today` |
| 演示 | `pages/kit-demo`（全组件全状态）+ `pages/kit-map`（行程首页整页：地图 + 导航栏 + 徽标 + 三档抽屉 + 节点卡 + 离线切换） |

## 1. 目录结构

```
kit/
├─ app.js / app.json / app.wxss / project.config.json / sitemap.json   # 演示工程（touristappid），不要覆盖你的项目
├─ styles/
│  ├─ tokens.wxss      # 设计令牌：page{} 上的 CSS 变量
│  ├─ icons.wxss       # 自绘线性图标（SVG data URI），.xj-icon--{name}-{color}
│  └─ index.wxss       # 入口：@import tokens + icons
├─ components/         # 20 个组件，每个含 index.wxml/.wxss/.js/.json
│  ├─ xj-nav-bar  xj-button  xj-chip  xj-score-chip  xj-quality-badge
│  ├─ xj-itinerary-card  xj-transit  xj-empty-slot  xj-day-tabs
│  ├─ xj-alert-bar  xj-offline-bar  xj-chat-bar  xj-toast
│  ├─ xj-bottom-sheet  xj-node-card  xj-conflict-preview
│  └─ xj-skeleton  xj-trip-item  xj-import-result  xj-empty-state
├─ utils/map-style.js  # <map> marker / polyline 常量与工厂函数
├─ assets/markers/     # 地图标注 PNG（64×64 @2x；current 72×72）
├─ assets/icons/svg/   # 图标源文件（设计参考，运行时不需要）
├─ pages/kit-demo/     # 组件全状态演示
├─ pages/kit-map/      # 行程首页整页演示
├─ spec.png / spec.html
├─ build_kit.py / build_v2.py   # 生成脚本（改 token/图标后可重新生成）
└─ README.md
```

## 2. 设计原则（必须遵守）

1. **两种橙色，分工严格**
   - **CTA 橙 `--xj-cta` #C2410C**：页面唯一主按钮（`xj-button type="primary"`）。白字对比度 5.18:1。
   - **地图橙 `--xj-accent` #FF7A45**：只用于**图形**——当天路线、当前位置、地图选中点、与选中点联动的卡片描边（`active`）。**不得承载文字**，不得用于按钮底色。
   - 其他强调一律用藏青。
2. **藏青 `#1E3A6E` 承载品牌与 Agent**：次级按钮、选中态、发送按钮、质量徽标分数。
3. **状态色与品牌色分离**：锁定/通过=绿 #1F7A52，冲突/草稿/风险=琥珀（文字 #7A5200），错误/降级/离线=红 #B42318（离线条为深灰底）。
4. **单一提醒位**：地图上方/抽屉顶部同一时间只显示一条提醒；toast 临时替代，不叠加。地图上只常驻**质量徽标**一个浮层（不再有透视开关、图例 chip）。
5. **扁平 + 暖白**：页面底 #F7F5F0，卡片白底 + 2rpx 描边或轻阴影；禁止新拟态。
6. **8rpx 栅格**；圆角 16 / 24 / 32 / 999。
7. **手势规则**：抽屉只能拖顶部把手和 Day Tab 那一行（`header` 插槽）；排序只能长按「⋮⋮」再拖（由页面实现）；全屏抽屉内列表只滚动。
8. **不静默**：「仍然加入」的节点必须 `conflict` 标红写原因；估算的交通必须 `estimated`（≈）；未定的餐必须 `xj-empty-slot`（午餐 · 待定），不能留空。
9. **删除不弹确认**，用 `xj-toast` 撤销（5 秒）；例外：我的行程列表真删除需二次确认（无撤销）。

## 3. 设计令牌（styles/tokens.wxss）

全部定义在 `page {}`；组件 `styleIsolation: 'apply-shared'`，通过 CSS 变量继承读取。

| 类别 | 变量 | 值 | 用途 |
|---|---|---|---|
| 主色 | `--xj-primary` / `--xj-primary2` / `--xj-primary-light` | #1E3A6E / #2F5597 / #E6ECF6 | 品牌、次级按钮、选中 |
| CTA | `--xj-cta` / `--xj-cta-pressed` / `--xj-cta-light` | #C2410C / #9A3412 / #FDEBE1 | 主按钮（唯一） |
| 地图橙 | `--xj-accent` / `--xj-accent-light` | #FF7A45 / #FFEDE4 | 仅地图图形 & active 描边 |
| 背景/卡片 | `--xj-bg` / `--xj-card` | #F7F5F0 / #FFFFFF | |
| 文字 | `--xj-text` / `--xj-text2` / `--xj-text3` | #1B2333 / #5F6878 / #666E7D | 正文 / 次要 / 辅助（均 ≥4.5） |
| 禁用 | `--xj-text-disabled` | #9AA1AD | **仅**禁用态、装饰线、虚线框 |
| 线 | `--xj-line` | #E8E4DC | |
| 成功 | `--xj-success` / `--xj-success-icon` / `--xj-success-light` | #1F7A52 / #2E9E6B / #E3F4EC | 锁定、通过、今天 |
| 预警 | `--xj-warn` / `--xj-warn-light` / `--xj-warn-text` | #E8A317 / #FFF5DC / #7A5200 | warn 只做图形，文字用 warn-text |
| 错误 | `--xj-error` / `--xj-error-light` | #B42318 / #FDECEC | 错误、降级、冲突节点 |
| 信息 | `--xj-info` / `--xj-info-light` | #2F5597 / #E6ECF6 | |
| 排除 | `--xj-exclude` | #F4F4F4 | |
| 圆角 | `--xj-radius-xs/sm/md/lg/xl/pill` | 8/16/24/32/44/999rpx | |
| 间距 | `--xj-space-1…6` | 8/16/24/32/40/48rpx | |
| 字号 | `--xj-font-h1/h2/h3/body/sm/caption/mini/num` | 48/36/32/30/26/24/22/40rpx | |
| 字重 | `--xj-weight-regular/medium/bold` | 400/500/700 | |
| 阴影 | `--xj-shadow-card/float/tab/cta/primary` | 见文件 | |
| 层级 | `--xj-z-map-overlay/sheet/chat/nav/popup/toast` | 10/20/30/40/100/1000 | |
| 尺寸 | `--xj-btn-h/btn-h-sm/chip-h/chat-h/nav-h/sheet-peek` | 88/64/64/100/88/300rpx | |

### 3.1 对比度（WCAG 2.1，正文 AA ≥ 4.5:1，图形 ≥ 3:1）

| 前景 / 背景 | 比值 | 结论 |
|---|---|---|
| 白 / CTA #C2410C | **5.18** | ✓ 主按钮 |
| 白 / CTA 按下 #9A3412 | 7.31 | ✓ |
| 白 / #FF7A45（v1 主按钮） | 2.59 | ✗ 已弃用为按钮色 |
| CTA #C2410C / bg #F7F5F0（作文字时） | 4.75 | ✓ |
| 白 / 藏青 #1E3A6E | 11.14 | ✓ |
| 藏青 / bg · 白 · primary-light | 10.22 · 11.14 · 9.38 | ✓ |
| text #1B2333 / bg | 14.44 | ✓ |
| text2 #5F6878 / bg · 白 | 5.16 · 5.62 | ✓ |
| text3 #666E7D / bg · 白 | **4.71 · 5.13** | ✓（v1 #9AA1AD 仅 2.39） |
| text-disabled #9AA1AD / bg · 白 | 2.39 · 2.60 | 仅禁用/装饰（WCAG 豁免），不可用于必要信息 |
| success #1F7A52 / 白 · 浅绿 | 5.30 · 4.65 | ✓ |
| warn-text #7A5200 / 浅黄 · 白 | 6.38 · 6.92 | ✓ |
| error #B42318 / 浅红 · 白 | 5.76 · 6.57 | ✓ |
| #FF7A45 路线 / 地图底 #EEF0EA | 2.25 | 图形 < 3:1 → 路线强制 2px 白描边、marker 白边 + 光晕补偿；真机需验证 |

## 4. 页面结构：行程页即首页

```
┌ xj-nav-bar（透明，左「我的行程」，中标题，右胶囊）
│  └ xj-quality-badge（地图左上唯一浮层，点 → Agent 透视面板）
├ <map> 全屏（当天路线 + 编号 marker）
├ xj-bottom-sheet（peek / half / full）
│   header 插槽：xj-day-tabs + 唯一提醒位（xj-alert-bar alerts | xj-offline-bar）
│   默认插槽：
│     · 列表：xj-itinerary-card / xj-transit / xj-empty-slot 交替
│     · 选中节点：xj-node-card（half）→ 展开玩法（full）
│     · 加点：xj-conflict-preview
├ xj-chat-bar（固定底部；离线 disabled）
└ xj-toast（改动 + 撤销，chat-bar 上方）
无行程时：抽屉 / 地图位置换为 xj-empty-state；加载中用 xj-skeleton。
「我的行程」页：xj-nav-bar(placeholder, 左按钮隐藏或返回) + xj-trip-item 列表 + xj-import-result（粘贴小红书）。
```

**Agent 透视入口（v2）**：不再有常驻开关。`xj-quality-badge` 的 `bind:tap` → 页面打开透视面板（建议 `xj-bottom-sheet level="full"` 或 page-container）；`xj-alert-bar` 中 `type:'quality'` 提醒的 action 也指向同一面板。演示时一步打开。

## 5. 接入现有原生项目（逐步）

### 5.1 文件拷贝映射

| 从 kit/ | 拷到你的项目（miniprogramRoot 下） | 必需 |
|---|---|---|
| `styles/` | `styles/` | ✅ |
| `components/xj-*` | `components/` | ✅ 可按需挑选；**依赖：xj-itinerary-card、xj-node-card → xj-score-chip** |
| `utils/map-style.js` | `utils/map-style.js` | 用 map 时 |
| `assets/markers/` | `assets/markers/` | 用 map 时（路径写死 `/assets/markers/`，改位置需改 `ICON_DIR`） |
| `pages/kit-demo`、`pages/kit-map` | 可选，调试参考 | ❌ |
| app.* / project.config.json | **不要覆盖** | ❌ |

### 5.2 app.wxss 第一行
```css
@import "styles/index.wxss";
```

### 5.3 注册组件（app.json 全局，推荐）
```json
{
  "usingComponents": {
    "xj-nav-bar": "/components/xj-nav-bar/index",
    "xj-button": "/components/xj-button/index",
    "xj-chip": "/components/xj-chip/index",
    "xj-score-chip": "/components/xj-score-chip/index",
    "xj-quality-badge": "/components/xj-quality-badge/index",
    "xj-itinerary-card": "/components/xj-itinerary-card/index",
    "xj-transit": "/components/xj-transit/index",
    "xj-empty-slot": "/components/xj-empty-slot/index",
    "xj-day-tabs": "/components/xj-day-tabs/index",
    "xj-alert-bar": "/components/xj-alert-bar/index",
    "xj-offline-bar": "/components/xj-offline-bar/index",
    "xj-chat-bar": "/components/xj-chat-bar/index",
    "xj-toast": "/components/xj-toast/index",
    "xj-bottom-sheet": "/components/xj-bottom-sheet/index",
    "xj-node-card": "/components/xj-node-card/index",
    "xj-conflict-preview": "/components/xj-conflict-preview/index",
    "xj-skeleton": "/components/xj-skeleton/index",
    "xj-trip-item": "/components/xj-trip-item/index",
    "xj-import-result": "/components/xj-import-result/index",
    "xj-empty-state": "/components/xj-empty-state/index"
  }
}
```

### 5.4 行程页（首页）配置
- app.json `pages` 第一项为行程页；**不要配置 `tabBar`**。
- 行程页 `index.json`：`{ "navigationStyle": "custom" }`。
- app.json `window`：`"backgroundColor": "#F7F5F0", "navigationBarBackgroundColor": "#F7F5F0", "navigationBarTextStyle": "black"`（其他页用原生导航栏）。

### 5.5 导入演示工程验证
开发者工具 → 导入 `kit/` → AppID 用测试号 / `touristappid` → `pages/kit-demo/index`，点顶部「打开行程页」看整页。

## 6. 组件 API

> 事件统一 `triggerEvent`，页面 `bind:事件名` 监听，数据在 `e.detail`。属性在 WXML 中用短横线写法（`actionText` → `action-text`）。所有组件均为**受控组件**（状态由页面传入），业务逻辑不进组件。

### 6.1 xj-nav-bar（自定义导航栏）
| 属性 | 类型 | 默认 | 说明 |
|---|---|---|---|
| title | String | '' | 标题（单行省略） |
| subtitle | String | '' | 副标题（如日期） |
| leftText | String | `我的行程` | 左侧入口文字 |
| showLeft | Boolean | true | |
| bg | String | `transparent` | 地图页透明；列表页传 `#F7F5F0` |
| placeholder | Boolean | false | 是否在文档流中占位（非地图页设 true） |

| 事件 | detail |
|---|---|
| left | `{}` |
| ready | `{ statusBarHeight, navHeight, totalHeight }`（px，用于设置抽屉 top-offset、浮层 top） |

实现：`wx.getWindowInfo().statusBarHeight` + `wx.getMenuButtonBoundingClientRect()`；导航高 = (胶囊 top − 状态栏) × 2 + 胶囊高；右侧留出 `windowWidth − 胶囊left + 8px`。
```xml
<xj-nav-bar title="北京 3 日游" subtitle="10/24 - 10/26" bind:left="goMyTrips" bind:ready="onNavReady"/>
```

### 6.2 xj-button
| 属性 | 类型 | 默认 | 说明 |
|---|---|---|---|
| type | String | `primary` | `primary`(CTA 橙 #C2410C) / `dark` / `secondary` / `text` |
| size | String | `md` | `md` 88rpx / `sm` 64rpx |
| block | Boolean | false | 通栏 |
| loading | Boolean | false | 转圈且不可点 |
| disabled | Boolean | false | |
| icon | String | '' | 图标类后缀，如 `spark-white` |
| openType | String | '' | 透传 open-type |

事件：`tap` → `{}`（loading/disabled 不触发）。默认插槽为文字。
```xml
<xj-button type="primary" icon="spark-white" loading="{{planning}}" bind:tap="onPlan">开始规划</xj-button>
```

### 6.3 xj-chip
| 属性 | 类型 | 默认 | 说明 |
|---|---|---|---|
| label | String | '' | |
| status | String | `default` | `default` / `selected` / `must` / `exclude` |
| size | String | `md` | `md` 64 / `sm` 52rpx |
| closable | Boolean | false | |
| value | any | null | 回传 |

事件：`tap` → `{ value, status }`；`close` → `{ value }`（不触发 tap）。

### 6.4 xj-score-chip（餐厅/POI 评分，中性）
| 属性 | 类型 | 默认 | 说明 |
|---|---|---|---|
| score | Number/String | '' | 4.7 |
| suffix | String | '' | 来源，如「大众点评」 |

事件：`tap` → `{ score }`。**不要**用于行程质量。

### 6.5 xj-quality-badge（行程质量 · 透视入口）
| 属性 | 类型 | 默认 | 说明 |
|---|---|---|---|
| score | Number | 0 | 评审分 |
| label | String | `评审` | |
| status | String | `auto` | `auto`（≥passLine → pass，否则 draft）/ `pass` / `draft` / `fail` |
| passLine | Number | 85 | |

外观：pass = 白底 + 绿盾 + 藏青分数；draft = 「草稿」琥珀标 + 琥珀深色分数；fail = 「未通过」红标。
事件：`tap` → `{ score, state }` → 打开 Agent 透视面板。
```xml
<xj-quality-badge score="{{trip.score}}" bind:tap="openInsight"/>
```

### 6.6 xj-itinerary-card
| 属性 | 类型 | 默认 | 说明 |
|---|---|---|---|
| time / duration | String | '' | `09:00` / `2.5h` |
| name / meta | String | '' | meta 单行省略 |
| locked | Boolean | false | 已锁定徽标 |
| rating | Number/String | '' | 餐厅评分（xj-score-chip） |
| active | Boolean | false | 地图橙描边，与 marker 联动 |
| dimmed | Boolean | false | 55% 透明（已过时/闭馆） |
| waitlist | Boolean | false | **候补**：虚线框 + 「候补」标（超容量自动放入） |
| conflict | String | '' | 非空 → 红框 + 原因（「仍然加入」后必须设置） |
| itemId | any | null | `item-id` |

事件：`tap` → `{ id }`；`longpress` → `{ id }`。插槽：`tag` / 默认 / `right`。
```xml
<xj-itinerary-card item-id="{{item.id}}" time="{{item.time}}" duration="{{item.duration}}" name="{{item.name}}"
  meta="{{item.meta}}" locked="{{item.locked}}" waitlist="{{item.waitlist}}" conflict="{{item.conflictReason}}"
  active="{{item.id===activeId}}" bind:tap="focusNode"/>
```

### 6.7 xj-transit
| 属性 | 类型 | 默认 | 说明 |
|---|---|---|---|
| mode | String | `walk` | `walk` / `subway` / `bus` / `taxi` / `bike` |
| text | String | '' | `地铁 5 号线 · 18 分钟` |
| estimated | Boolean | false | 估算：前缀「≈」、更稀的虚线、「估算」标 |

事件：`tap` → `{ mode, estimated }`。路线服务降级时所有段设 `estimated`。

### 6.8 xj-empty-slot（待定空位）
| 属性 | 类型 | 默认 |
|---|---|---|
| label | String | `午餐 · 待定` |
| time | String | '' |
| actionText | String | `去挑选 ›` |
| slotId | any | null |

事件：`tap` → `{ id }`（打开餐厅候选）。

### 6.9 xj-day-tabs
| 属性 | 类型 | 默认 | 说明 |
|---|---|---|---|
| days | Array | [] | `[{ label:'Day 1', sub:'周六', warn:false, today:false }]`；warn=琥珀点，today=「今天」 |
| current | Number | 0 | |

事件：`change` → `{ index }`。旅行日期内页面应自动选中今天。

### 6.10 xj-alert-bar（单一提醒位）
| 属性 | 类型 | 默认 | 说明 |
|---|---|---|---|
| alerts | Array | [] | `[{ id, type, text, actionText }]` |
| type / text / actionText | String | '' | 兼容单条用法 |
| closable | Boolean | false | 仅单条时显示 × |

`type` 与优先级：`error` / `degraded` / `offline`（1，红）> `quality`（2，琥珀）> `risk` / `warn`（3，琥珀）> `info`（4，蓝）。同级按数组顺序。
多条时右侧显示「N 条提醒 ⌄」，点开逐条列出，再点「收起」。

| 事件 | detail |
|---|---|
| action | `{ id, alert }` |
| toggle | `{ expanded }` |
| close | `{ id }` |
```xml
<xj-alert-bar alerts="{{alerts}}" bind:action="onAlertAction"/>
```
```js
alerts: [
  { id: 'deg', type: 'degraded', text: '路线服务降级，交通时间为估算', actionText: '重试' },
  { id: 'q', type: 'quality', text: '评审 78：午餐未定', actionText: '看透视' },
  { id: 'w', type: 'risk', text: '周日下午雷阵雨', actionText: '看备选' }
]
```
toast 出现时不需隐藏提醒位（toast 位于底部）；但不要再在地图上叠其他横幅。

### 6.11 xj-offline-bar（离线只读）
| 属性 | 类型 | 默认 |
|---|---|---|
| text | String | `离线 · 显示 10/18 14:20 的版本` |
| sub | String | `只读模式，联网后可修改` |
| actionText | String | `重试` |

事件：`retry`。离线时：放在提醒位（替代 alert-bar）；`xj-chat-bar disabled`；加地点、排序置灰；地图换为缓存的静态路线图（与导出每日图复用，页面实现）。

### 6.12 xj-chat-bar
| 属性 | 类型 | 默认 | 说明 |
|---|---|---|---|
| placeholder | String | `告诉行迹：下午想轻松点…` | |
| showMic | Boolean | true | |
| sending | Boolean | false | 发送中 |
| disabled | Boolean | false | 离线/只读 |
| fixed | Boolean | false | 固定底部 |
| bottom | Number | 44 | fixed 时距底 rpx |
| clearOnSend | Boolean | true | |

事件：`send` `{ value }`（trim，空不触发）、`input` `{ value }`、`focus`/`blur`（原生 detail）、`micstart`/`micend`。方法 `setValue(text)`。
UX 待办：点输入栏应展开半屏对话记录（每条改动带「看改动 / 撤销」）—— 可用 `xj-bottom-sheet` + 页面列表实现，本包未封装。

### 6.13 xj-toast（改动 + 撤销）
| 属性 | 类型 | 默认 | 说明 |
|---|---|---|---|
| bottom | Number | 180 | rpx，chat-bar 上方 |
| duration | Number | 5000 | ms，UX 规定 5 秒 |

方法：`show({ text, actionText='撤销', icon, duration, payload })`、`hide()`。
事件：`action` → `{ payload }`（点撤销）；`hide` → `{ reason:'timeout'|'action'|'manual', payload }`。
```js
this.selectComponent('#toast').show({ text: '已删除 前门大街', payload: { op: 'delete', id } });
```

### 6.14 xj-bottom-sheet（三档抽屉）
| 属性 | 类型 | 默认 | 说明 |
|---|---|---|---|
| level | String | `half` | `peek` / `half` / `full`（受控） |
| peekHeight | Number | 300 | rpx |
| halfRatio | Number | 0.52 | 半屏占窗口高 |
| topOffset | Number | 0 | px，full 时距顶（传 nav-bar `totalHeight`） |
| headerHeight | Number | 160 | rpx，用于计算滚动区高度 |
| bottomPad | Number | 180 | rpx，列表底部为 chat-bar 留白 |
| scrollAlways | Boolean | false | 默认仅 full 档列表可滚动 |

插槽：`header`（把手下方，**可拖**，放 Day Tab + 提醒位）、默认（列表，**不可拖**）。
事件：`change` → `{ level }`；`scrolltolower`。方法 `setLevel(level)`。快速轻扫（>0.6px/ms）跳一档，否则吸附最近档。
```xml
<xj-bottom-sheet level="{{level}}" top-offset="{{navH}}" bind:change="onLevel">
  <view slot="header"><xj-day-tabs days="{{days}}" current="{{day}}" bind:change="onDay"/><xj-alert-bar alerts="{{alerts}}"/></view>
  ...列表 / 节点卡...
</xj-bottom-sheet>
```

### 6.15 xj-node-card（合并节点卡 / 玩法卡）
| 属性 | 类型 | 默认 | 说明 |
|---|---|---|---|
| index | Number/String | 1 | 编号 |
| name / time / duration / meta | String | '' | |
| rating | Number/String | '' | |
| locked | Boolean | false | |
| tip | String | '' | 一句避坑 |
| expanded | Boolean | false | 展开为玩法卡（建议与抽屉 full 同步） |
| playDuration | String | '' | 主线时长 |
| steps | Array | [] | `[{ title, desc, time, branch }]`，branch=支线（空心点） |
| itemId | any | null | |

插槽：`play`（玩法区追加）、默认。
事件：`action` → `{ act:'lock'|'replace'|'delete', id }`；`expand` → `{ expanded, id }`；`close` → `{ id }`。
规则：选支线会改变当天时长 → 先 `xj-conflict-preview` 预览再应用。删除 → 直接执行 + toast 撤销。

### 6.16 xj-conflict-preview（加点冲突预览）
| 属性 | 类型 | 默认 | 说明 |
|---|---|---|---|
| title | String | `加入后会影响当天安排` | |
| dayLabel | String | `Day 1 结束时间` | |
| before / after | String | '' | 前后对比 |
| over | Boolean | false | after 越界 → 红 |
| impacts | Array | [] | `[{ text, level:'warn'|'error'|'info' }]` |
| applyText | String | `按建议调整` | 主操作（藏青） |
| forceText | String | `仍然加入` | 次操作 |

事件：`apply`、`force`。`force` 后该节点 `xj-itinerary-card conflict="原因"`。「加到哪一天」默认当前 Day Tab（页面实现）。

### 6.17 xj-skeleton
| 属性 | 类型 | 默认 |
|---|---|---|
| type | String | `card`（`card` / `text` / `map`） |
| rows | Number | 3 |
| height | Number | 400（map，rpx） |
| animate | Boolean | true |

### 6.18 xj-trip-item（我的行程）
| 属性 | 类型 | 默认 | 说明 |
|---|---|---|---|
| city / dates / summary | String | '' | |
| days | Number | 0 | |
| status | String | `draft` | `draft` 规划中 / `confirmed` 待出发 / `ongoing` 旅行中 / `traveled` 已结束（按日期自动判断） |
| cover | String | '' | CSS background（可渐变） |
| tripId | any | null | |

事件：`tap` / `longpress` → `{ id }`。左滑删除 + 二次确认由页面实现（如 `movable-area`）。

### 6.19 xj-import-result（小红书导入）
| 属性 | 类型 | 默认 | 说明 |
|---|---|---|---|
| source | String | `小红书` | |
| title | String | '' | 笔记标题 |
| places | Array | [] | `[{ name, note, matched, checked }]`；未匹配显示「去确认」 |
| confirmText | String | `加入想去清单` | |

事件：`change` `{ index, checked }`、`fix` `{ index }`、`origin`（复制原笔记链接 → toast「已复制，到小红书粘贴打开」）、`confirm` `{ places }`（已匹配且勾选）。

### 6.20 xj-empty-state（无行程）
| 属性 | 类型 | 默认 |
|---|---|---|
| kicker | String | `行迹 · 你的旅行搭子` |
| title | String | `想去哪儿？` |
| sub | String | `一句话告诉我，Agent 帮你排好每一天` |
| prompts | Array | 3 条示例提示词 |

事件：`prompt` → `{ text }`（填入 chat-bar 或直接发送）。默认插槽放主按钮。插画为纯 CSS 渐变，无图片。

## 7. 图标（styles/icons.wxss）
```xml
<view class="xj-icon xj-icon--lock-green"></view>
<view class="xj-icon xj-icon--map-navy" style="--xj-icon-size:48rpx"></view>
```
- 名称：lock star mic send spark walk subway bus taxi bike warn info error close map trip me check list chevron up undo offline clock link shield drag trash refresh
- 颜色：navy orange grey white green amber red blue dark
- 默认 36rpx。新增：`assets/icons/svg/` 放 24×24 线性 SVG，在 `build_kit.py` 的 `P` 字典中加入并重新生成。

## 8. 地图 marker / polyline

| 文件 | 用途 |
|---|---|
| `poi-orange-1…20.png` | 当天编号景点 |
| `poi-navy-1…20.png` | 其他天编号景点 |
| `restaurant.png` / `restaurant-orange.png` | 餐厅（其他天 / 当天） |
| `hotel.png` | 酒店 |
| `current.png` | 当前位置（72×72） |

`utils/map-style.js`：`COLOR, MARKER_SIZE(32px), ICON_DIR, POLYLINE_CURRENT(#FF7A45 w6 白边2 箭头), POLYLINE_OTHER(藏青35% w4 虚线), POLYLINE_WALK, poiMarker(id,lat,lng,index,{current,extra}), typeMarker(id,lat,lng,type,extra), routeLine(points,kind)`。

```js
const { poiMarker, typeMarker, routeLine } = require('../../utils/map-style.js');
renderDay(day, allDays) {
  const markers = [];
  allDays.forEach((d, di) => d.items.forEach((p, i) => {
    const current = di === day;
    markers.push(p.type === 'restaurant'
      ? typeMarker(p.id, p.lat, p.lng, current ? 'restaurant-orange' : 'restaurant')
      : p.type === 'hotel' ? typeMarker(p.id, p.lat, p.lng, 'hotel')
      : poiMarker(p.id, p.lat, p.lng, i + 1, { current }));
  }));
  const polyline = allDays.map((d, di) => routeLine(d.items.map(p => ({ latitude: p.lat, longitude: p.lng })), di === day ? 'current' : 'other'));
  this.setData({ markers, polyline });
}
```
```xml
<map class="map" markers="{{markers}}" polyline="{{polyline}}" bindmarkertap="onMarker"/>
```
- marker `id` 必须为数字。点 marker → `xj-node-card` + 抽屉 half + 对应卡片 `active`。
- 原生 `<map>` 上叠普通 view 依赖同层渲染（基础库 ≥2.8）。若在低版本出现遮挡，改用 `cover-view` 自行实现浮层（UX 建议地图上浮层越少越好，本设计仅一个徽标）。
- 微信 `<map>` 用腾讯底图；高德只用于取 POI/路径数据（GCJ-02 一致）。
- 离线：原生 map 可能无法加载瓦片，换成缓存静态路线图（canvas 绘制，可复用导出图）。

## 9. Do / Don't

| ✅ Do | ❌ Don't |
|---|---|
| 主按钮用 `xj-button type="primary"`（#C2410C），一屏一个 | 用 #FF7A45 做按钮底或文字 |
| 地图上只有当天路线/当前点/选中点用 #FF7A45 | 其他天路线也用橙 |
| 质量用 `xj-quality-badge`，餐厅评分用 `xj-score-chip` | 混用；评分用橙色 |
| 提醒统一进 `xj-alert-bar alerts` | 地图上叠多条横幅 / 常驻透视开关 / 图例 chip |
| 删除用 toast 撤销（5 秒） | 删除节点弹确认框 |
| 估算段 `estimated`、未定餐 `xj-empty-slot`、强加节点 `conflict` | 静默处理、留空 |
| 辅助文字用 `--xj-text3` (#666E7D) | 用 `--xj-text-disabled` 写必要信息 |
| 颜色/字号用 `var(--xj-*)`，尺寸 rpx 8 倍数 | 写死色值、px |
| 页面中给组件包一层 view 再加 margin | 在页面 wxss 用 `xj-xxx{}` 标签选择器 |

## 10. 常见问题 / 排错

| 现象 | 解决 |
|---|---|
| 组件无颜色 / 图标不显示 | app.wxss 未 `@import "styles/index.wxss"` 或路径错（注意 miniprogramRoot） |
| `Component is not found in path` | usingComponents 写 `/components/xj-xxx/index`（无扩展名）；xj-itinerary-card / xj-node-card 需同时拷 xj-score-chip |
| 导航栏和胶囊不对齐 | 页面 json 未设 `navigationStyle: custom`；或在 PC 端预览（胶囊信息不同），以真机为准 |
| 抽屉高度不对 / 遮住导航 | 把 `xj-nav-bar` 的 `ready.totalHeight` 传给 `top-offset` |
| 抽屉内列表拖不动 | 设计如此：只有 header 可拖；full 档列表才滚动（或设 `scroll-always`） |
| 徽标被地图盖住 | 同层渲染不可用的低版本 → 改 cover-view |
| marker 不显示 / 点击无反应 | iconPath 以 `/` 开头；width/height 32；id 为 Number |
| toast 不出现 | 需 `id="toast"` 并 `this.selectComponent('#toast').show(...)` |
| alert-bar 不显示 | `alerts` 为空且未传 `text` 时组件不渲染（预期） |
| 老机型元素无间距 | 组件使用 flex `gap`（iOS ≥14.5）；需兼容时替换为 margin |
| 键盘顶起 chat-bar 异常 | 默认 adjust-position；自管时监听 focus 的 `detail.height` |
| Skyline 下表现不同 | 本包按 WebView 验证，页面 json 可设 `"renderer": "webview"` |

## 11. 给 Codex 的提示词（直接粘贴）

```
你在一个原生微信小程序项目中实现「行迹」界面，UI 必须使用仓库内行迹 UI Kit v2（styles/、components/xj-*、utils/map-style.js、assets/markers/）。规则：
1. app.wxss 首行 @import "styles/index.wxss"；app.json 全局注册 README 5.3 的 20 个组件（路径 /components/<name>/index）。不配置 tabBar。
2. 不修改 components/ 与 styles/；页面样式只用 var(--xj-*) 令牌，尺寸 rpx（设计稿 px×2），8rpx 栅格，不写死色值；不在页面 wxss 用组件标签选择器。
3. 颜色：主按钮 xj-button type="primary"（CTA 橙 #C2410C，一屏一个）；#FF7A45(--xj-accent) 只用于地图当天路线/当前位置/选中点及卡片 active 描边，不用于文字和按钮；辅助文字用 --xj-text3。
4. 行程页即首页（navigationStyle: custom）：xj-nav-bar（左「我的行程」）→ 全屏 <map>（marker/polyline 用 map-style.js 的 poiMarker/typeMarker/routeLine，当天 current，其他天 other）→ 地图左上只放 xj-quality-badge（点击打开 Agent 透视面板，没有常驻透视开关）→ xj-bottom-sheet（top-offset=nav totalHeight；header 插槽放 xj-day-tabs + 唯一提醒位：在线 xj-alert-bar alerts，离线 xj-offline-bar）→ 列表 xj-itinerary-card / xj-transit / xj-empty-slot 交替 → 选中节点显示 xj-node-card（half），展开玩法切 full → xj-chat-bar 固定底部（离线 disabled）→ xj-toast（改动/删除带撤销，5 秒）。无行程时显示 xj-empty-state；加载用 xj-skeleton。
5. 「我的行程」页：xj-trip-item 列表（状态按日期自动：draft/confirmed/ongoing/traveled）+ 小红书粘贴导入 xj-import-result。
6. 加点先展示 xj-conflict-preview；「仍然加入」后该节点 xj-itinerary-card 设置 conflict 原因；超容量的点 waitlist；估算交通 estimated；未定餐用 xj-empty-slot。
7. 组件均为受控：通过 properties 传状态，监听 bind:tap/change/send/action/force/apply/expand/prompt/confirm/left/ready，在页面 setData。事件数据见 README 第 6 节。业务逻辑写在页面/服务层。
8. 完成后按 README 第 12 节检查清单自检，参照 pages/kit-map 的整页结构。
```

## 12. 接入检查清单

- [ ] `styles/`、需要的 `components/xj-*`（含依赖 xj-score-chip）、`utils/map-style.js`、`assets/markers/` 已拷入 miniprogramRoot
- [ ] app.wxss 首行 `@import "styles/index.wxss";`
- [ ] app.json 注册组件，无 tabBar；行程页为首页且 `navigationStyle: custom`
- [ ] 开发者工具无 "Component is not found" / WXSS 编译错误
- [ ] 导航栏「我的行程」与胶囊垂直居中对齐，右侧不遮挡胶囊（iOS + Android 真机）
- [ ] 主按钮为 #C2410C；页面中无 #FF7A45 文字/按钮；地图只有当天路线为橙
- [ ] 地图上只有一个浮层（质量徽标）；点徽标打开透视面板
- [ ] 提醒位同时只显示一条，多条显示「N 条提醒」
- [ ] 抽屉三档可拖（只拖 header），full 档列表可滚动，不与地图平移冲突
- [ ] 删除节点 → toast「撤销」5 秒后消失；撤销生效
- [ ] 离线：显示 offline-bar，chat-bar 置灰，不可修改
- [ ] 估算段带 ≈；午餐待定不留空；强加节点标红
- [ ] marker 32px 清晰，点击得到数字 id 并联动节点卡
- [ ] 页面 wxss 中搜索 `#` 色值为 0

## 13. 已知限制

- 仅视觉组件；Agent 透视面板内容、对话记录半屏、拖动排序、左滑删除、导出每日图、离线静态地图由页面实现（样式参考 spec.png / UX 线框）。
- `xj-bottom-sheet` 用 touch + transform 实现（WebView），极低端机可能掉帧；如需更顺滑可改 WXS 响应事件。
- flex `gap` 需 iOS ≥14.5 / 较新 Android WebView。
- 已做静态校验（JS 语法、JSON、WXML 标签、路径/图片/图标类、WXSS 无 `*`/属性选择器/外链/字体）+ 新建工程按本文接入验证 + 部分组件逻辑 Node 单测；**尚未在微信开发者工具/真机运行**，首次导入以工具报错为准。
- #FF7A45 路线与地图底对比 2.25:1（< 3:1 图形标准），依赖白描边补偿，需真机户外验证。
