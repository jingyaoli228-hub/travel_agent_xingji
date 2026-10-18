# 东京三日计划工作台演示

1. Planner 生成东京三日草案，页面从聊天模式切换为“对话 + 日期行程 + 地图”。
2. 用户选择第二天；中栏只显示 `day_2`，地图先清除旧覆盖物，再加载第二天 Marker、真实路线并 `fitBounds`。
3. 用户点击下午两个活动之间的“＋”，搜索“唱片店”。后端把查询限制在东京并只返回有 Google `place_id` 的结果。
4. 用户选择唱片店。系统读取 Place Details，计算前后两段 Routes，发现后续活动需要顺延 40 分钟。
5. 页面显示 patch 预览：新增唱片店、顺延项目、交通变化和预算变化；正式 plan version 仍不变。
6. 用户确认。后端以 `plan_version + request_id` 提交，只替换第二天，唱片店标记 `user_locked=true`。
7. ConstraintValidator 和四项 TripCraft 指标重新执行，响应带回新版本、第二天计划和路线段。
8. 前端仅更新第二天，Marker 与 polyline 同步刷新；第一天和第三天对象保持不变。
