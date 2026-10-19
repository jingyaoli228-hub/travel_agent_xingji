// 体验版走腾讯云真实后端。访问凭证只存在本机忽略文件中，不提交到 Git。
let privateConfig = {}
try { privateConfig = require('./config.private') } catch (_) {}

module.exports = {
  transport: "remote",
  apiBaseUrl: privateConfig.apiBaseUrl || "https://tapes-sleeve-sewing-msie.trycloudflare.com",
  trialAccessKey: privateConfig.trialAccessKey || ""
}
