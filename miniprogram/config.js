// API origin may be overridden by an ignored local config; authentication is wx.login only.
let privateConfig = {}
try { privateConfig = require('./config.private') } catch (_) {}

module.exports = {
  transport: "remote",
  apiBaseUrl: privateConfig.apiBaseUrl || "https://travel.example.com",
  authMode: privateConfig.authMode || "wechat",
  trialAccessKey: privateConfig.trialAccessKey || ""
}
