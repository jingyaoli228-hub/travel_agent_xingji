function pad(value) { return String(value).padStart(2, '0') }

function dateOffset(offset) {
  const date = new Date()
  date.setHours(12, 0, 0, 0)
  date.setDate(date.getDate() + offset)
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function item(id, time, name, latitude, longitude, duration, reason, extra) {
  return Object.assign({
    item_id: id,
    time,
    activity: 'attraction',
    item_type: 'attraction',
    name,
    location: name,
    city: '北京',
    place_id: `amap-${id}`,
    latitude,
    longitude,
    duration_minutes: duration,
    rating: 4.7,
    reason,
    user_locked: false
  }, extra || {})
}

function route(id, from, to, mode, duration, distance, points) {
  return {
    segment_id: id,
    from_item_id: from,
    to_item_id: to,
    travel_mode: mode,
    duration_minutes: duration,
    distance_meters: distance,
    polyline: points.map(point => ({ lat: point[0], lng: point[1] })),
    status: 'REAL_ROUTE',
    warning: null
  }
}

function buildDemoTrip(tripId) {
  const days = [
    {
      day_number: 1, day_id: 'day_1', date: dateOffset(0), city: '北京', accommodation: '前门附近',
      items: [
        item('d1-temple', '09:00', '天坛公园', 39.8822, 116.4066, 120, '从中轴线南端开始，上午光线和体力都更合适', { user_locked: true }),
        item('d1-qianmen', '12:10', '前门大街', 39.8998, 116.3978, 90, '顺路吃午饭，减少折返'),
        item('d1-palace', '14:20', '故宫博物院', 39.9163, 116.3972, 150, '核心必看，已预留完整参观时段', { user_locked: true }),
        item('d1-jingshan', '17:20', '景山公园', 39.9255, 116.3966, 60, '登高看中轴线与日落')
      ]
    },
    {
      day_number: 2, day_id: 'day_2', date: dateOffset(1), city: '北京', accommodation: '前门附近',
      items: [
        item('d2-summer', '09:00', '颐和园', 39.9997, 116.2755, 180, '上午游园更舒适，给昆明湖留足时间', { user_locked: true }),
        item('d2-yuanming', '13:40', '圆明园', 40.0081, 116.2981, 120, '与颐和园同片区，避免跨城折返'),
        item('d2-pku', '16:20', '北京大学东门', 39.9928, 116.3152, 50, '只安排外观与周边散步，不把未核实预约写成已可进入')
      ]
    },
    {
      day_number: 3, day_id: 'day_3', date: dateOffset(2), city: '北京', accommodation: '前门附近',
      items: [
        item('d3-lama', '09:30', '雍和宫', 39.9473, 116.4173, 90, '错开早高峰后进入'),
        item('d3-guozijian', '11:20', '孔庙和国子监博物馆', 39.9464, 116.4170, 90, '步行即可衔接的人文路线'),
        item('d3-houhai', '14:20', '什刹海', 39.9416, 116.3880, 120, '下午安排胡同与水岸慢行'),
        item('d3-nanluo', '17:00', '南锣鼓巷', 39.9371, 116.4030, 70, '作为返程前的弹性收尾')
      ]
    }
  ]

  const routes = {
    day_1: [
      route('r-d1-1', 'd1-temple', 'd1-qianmen', 'BICYCLE', 18, 2700, [[39.8822, 116.4066], [39.8908, 116.4015], [39.8998, 116.3978]]),
      route('r-d1-2', 'd1-qianmen', 'd1-palace', 'WALK', 22, 1700, [[39.8998, 116.3978], [39.9078, 116.3974], [39.9163, 116.3972]]),
      route('r-d1-3', 'd1-palace', 'd1-jingshan', 'WALK', 15, 900, [[39.9163, 116.3972], [39.9212, 116.3969], [39.9255, 116.3966]])
    ],
    day_2: [
      route('r-d2-1', 'd2-summer', 'd2-yuanming', 'DRIVE', 20, 7200, [[39.9997, 116.2755], [40.0038, 116.2860], [40.0081, 116.2981]]),
      route('r-d2-2', 'd2-yuanming', 'd2-pku', 'BICYCLE', 18, 2600, [[40.0081, 116.2981], [39.9992, 116.3065], [39.9928, 116.3152]])
    ],
    day_3: [
      route('r-d3-1', 'd3-lama', 'd3-guozijian', 'WALK', 8, 520, [[39.9473, 116.4173], [39.9468, 116.4171], [39.9464, 116.4170]]),
      route('r-d3-2', 'd3-guozijian', 'd3-houhai', 'TRANSIT', 24, 4100, [[39.9464, 116.4170], [39.9442, 116.4021], [39.9416, 116.3880]]),
      route('r-d3-3', 'd3-houhai', 'd3-nanluo', 'BICYCLE', 16, 2200, [[39.9416, 116.3880], [39.9402, 116.3957], [39.9371, 116.4030]])
    ]
  }

  return {
    trip_id: tripId,
    title: '北京 3 日游',
    subtitle: `${days[0].date.slice(5)} - ${days[2].date.slice(5)}`,
    status: 'confirmed',
    ongoing: true,
    plan_version: 1,
    quality: { score: 91, passed: true, issues: [] },
    days,
    route_segments_by_day: routes,
    alerts: [
      { id: 'risk', type: 'risk', text: '故宫与热门场馆开放时间请在出发前再次核实', actionText: '查看' }
    ],
    conversation_history: [
      { role: 'user', content: '北京三天，第一次去，想看经典景点，但不要太赶。' },
      { role: 'assistant', content: '已按中轴线、海淀和胡同三个片区拆分，优先减少跨区折返。' }
    ],
    changes: [],
    created_at: Date.now(),
    updated_at: Date.now()
  }
}

const placeCatalog = [
  ['故宫博物院', '北京市东城区景山前街4号', 39.9163, 116.3972, '博物馆'],
  ['景山公园', '北京市西城区景山西街44号', 39.9255, 116.3966, '公园'],
  ['中国国家博物馆', '北京市东城区东长安街16号', 39.9051, 116.4011, '博物馆'],
  ['北海公园', '北京市西城区文津街1号', 39.9254, 116.3890, '公园'],
  ['恭王府', '北京市西城区前海西街17号', 39.9370, 116.3864, '人文古迹'],
  ['798艺术区', '北京市朝阳区酒仙桥路2号', 39.9841, 116.4957, '艺术区'],
  ['北京环球度假区', '北京市通州区', 39.8560, 116.6740, '主题乐园'],
  ['八达岭长城', '北京市延庆区G6京藏高速58号出口', 40.3598, 116.0200, '人文古迹'],
  ['慕田峪长城', '北京市怀柔区渤海镇', 40.4319, 116.5704, '人文古迹'],
  ['鼓楼', '北京市东城区钟楼湾胡同', 39.9408, 116.3938, '人文古迹'],
  ['天坛公园', '北京市东城区天坛东里甲1号', 39.8822, 116.4066, '公园'],
  ['雍和宫', '北京市东城区雍和宫大街12号', 39.9473, 116.4173, '人文古迹']
].map((row, index) => ({
  place_id: `demo-place-${index + 1}`,
  name: row[0], address: row[1], latitude: row[2], longitude: row[3], type: row[4],
  rating: Number((4.9 - (index % 5) * 0.1).toFixed(1)), distance_meters: 800 + index * 430
}))

module.exports = { buildDemoTrip, placeCatalog, dateOffset }
