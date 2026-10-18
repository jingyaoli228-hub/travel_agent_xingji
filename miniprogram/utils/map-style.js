/* 行迹 · <map> 组件样式常量（微信原生 map，腾讯底图；高德 SDK 仅取数据时同样适用） */
const COLOR = { primary: '#1E3A6E', accent: '#FF7A45', other: '#1E3A6E59', white: '#FFFFFF', mapBg: '#EEF0EA', grid: '#D8DCD4' };
const MARKER_SIZE = { width: 32, height: 32 }; // px，图片为 64x64 @2x
const ICON_DIR = '/assets/markers/';
// 当天（选中天）路线：唯一使用暖橙
const POLYLINE_CURRENT = { color: '#FF7A45FF', width: 6, borderColor: '#FFFFFFFF', borderWidth: 2, arrowLine: true, level: 'abovelabels' };
// 其他天：藏青 35% 虚线
const POLYLINE_OTHER = { color: '#1E3A6E59', width: 4, dottedLine: true, level: 'abovelabels' };
// 步行接驳段
const POLYLINE_WALK = { color: '#FF7A45B3', width: 4, dottedLine: true, level: 'abovelabels' };
// P0 产品决定：不同交通方式分色；颜色只承载地图图形，不用于按钮/正文。
const POLYLINE_BY_MODE = {
  WALK: { color: '#FF7A45FF', width: 5, dottedLine: true, borderColor: '#FFFFFFFF', borderWidth: 1, level: 'abovelabels' },
  TRANSIT: { color: '#1E3A6EFF', width: 6, borderColor: '#FFFFFFFF', borderWidth: 2, level: 'abovelabels' },
  DRIVE: { color: '#7A5200FF', width: 6, borderColor: '#FFFFFFFF', borderWidth: 2, arrowLine: true, level: 'abovelabels' },
  BICYCLE: { color: '#1F7A52FF', width: 5, dottedLine: true, borderColor: '#FFFFFFFF', borderWidth: 1, level: 'abovelabels' },
  FERRY: { color: '#2F5597FF', width: 5, dottedLine: true, level: 'abovelabels' },
  FLIGHT: { color: '#666E7DFF', width: 4, dottedLine: true, level: 'abovelabels' }
};
const POLYLINE_FALLBACK = { color: '#E8A317FF', width: 4, dottedLine: true, level: 'abovelabels' };

function poiMarker(id, latitude, longitude, index, opts = {}) {
  const current = opts.current !== false; // 属于当天 → 橙色，否则藏青
  const n = Math.min(Math.max(index, 1), 20);
  return Object.assign({
    id, latitude, longitude,
    iconPath: `${ICON_DIR}poi-${current ? 'orange' : 'navy'}-${n}.png`,
    width: MARKER_SIZE.width, height: MARKER_SIZE.height,
    anchor: { x: 0.5, y: 0.5 }, zIndex: current ? 20 : 10
  }, opts.extra || {});
}
function typeMarker(id, latitude, longitude, type, extra = {}) {
  // type: restaurant | restaurant-orange | hotel | current
  const size = type === 'current' ? { width: 36, height: 36 } : MARKER_SIZE;
  return Object.assign({ id, latitude, longitude, iconPath: `${ICON_DIR}${type}.png`, anchor: { x: 0.5, y: 0.5 }, zIndex: type === 'current' ? 30 : 15 }, size, extra);
}
function routeLine(points, kind = 'current') {
  const base = kind === 'current' ? POLYLINE_CURRENT : kind === 'walk' ? POLYLINE_WALK : POLYLINE_OTHER;
  return Object.assign({ points }, base);
}
function routeLineByMode(points, mode = 'TRANSIT', status = 'REAL_ROUTE') {
  const base = status === 'REAL_ROUTE' ? (POLYLINE_BY_MODE[String(mode).toUpperCase()] || POLYLINE_BY_MODE.TRANSIT) : POLYLINE_FALLBACK;
  return Object.assign({ points }, base);
}
module.exports = { COLOR, MARKER_SIZE, ICON_DIR, POLYLINE_CURRENT, POLYLINE_OTHER, POLYLINE_WALK, POLYLINE_BY_MODE, POLYLINE_FALLBACK, poiMarker, typeMarker, routeLine, routeLineByMode };
