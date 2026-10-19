// P0 体验版不依赖外部域名：所有可交互状态按行程拆分保存在本机。
// 获得已备案域名后，将 transport 改为 "remote" 并填写 apiBaseUrl 即可切回真实后端。
module.exports = {
  transport: "local-demo",
  apiBaseUrl: ""
}
