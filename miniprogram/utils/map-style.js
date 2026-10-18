/* 行迹 · <map> 组件样式常量（微信原生 map，腾讯底图；高德 SDK 仅取数据时同样适用） */
const COLOR = { primary: '#1E3A6E', accent: '#FF7A45', other: '#1E3A6E59', white: '#FFFFFF' };
const MARKER_SIZE = { width: 32, height: 32 }; // px，图片为 64x64 @2x
const ICON_DIR = '/assets/markers/';
// 当天（选中天）路线：唯一使用暖橙
const POLYLINE_CURRENT = { color: '#FF7A45FF', width: 6, borderColor: '#FFFFFFFF', borderWidth: 2, arrowLine: true, level: 'abovelabels' };
// 其他天：藏青 35% 虚线
const POLYLINE_OTHER = { color: '#1E3A6E59', width: 4, dottedLine: true, level: 'abovelabels' };
// 步行接驳段
const POLYLINE_WALK = { color: '#FF7A45B3', width: 4, dottedLine: true, level: 'abovelabels' };

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
module.exports = { COLOR, MARKER_SIZE, ICON_DIR, POLYLINE_CURRENT, POLYLINE_OTHER, POLYLINE_WALK, poiMarker, typeMarker, routeLine };
