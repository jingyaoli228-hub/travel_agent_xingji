# 行迹 P0 自用手机通路部署

该仓库已提供微信登录、只允许所有者 OpenID 的短期 API 令牌、容器健康检查/自动恢复和告警入口。要让真实手机连通，还必须由部署者提供微信和公网入口配置；这些账号密钥不应提交到 Git 或小程序包。

1. 在服务器复制 `.env.example` 为 `.env`，填好数据库密码及连接串、模型/地图服务密钥、`WECHAT_APP_ID`、`WECHAT_APP_SECRET`、`OWNER_OPENID`。`AUTH_TOKEN_SECRET` 应使用长随机值，不复用微信 AppSecret。
2. 在 Cloudflare 创建 Tunnel，并在 Public Hostname 中把自有域名路由到 `http://gateway:80`；把 Tunnel token 写入 `.env` 的 `CLOUDFLARE_TUNNEL_TOKEN`。保留网关仅绑定 `127.0.0.1:8080`，不直接把 API/数据库端口暴露到公网。
3. 将 Tunnel hostname 配为小程序 `miniprogram/config.private.js` 中的 `apiBaseUrl`，并在微信公众平台把同一个 HTTPS 域名登记为 request 合法域名。私有配置不得包含旧 `trialAccessKey`；预检会拒绝该字段。
4. 在服务器部署工作副本中填写 `.env` 的 `PUBLIC_API_BASE_URL`（同一个稳定 HTTPS origin），并确认忽略 Git 的 `miniprogram/config.private.js` 中 `apiBaseUrl` 与之完全一致。配置 `HEALTH_ALERT_WEBHOOK_URL` 后先运行 `python scripts/preflight_public_deploy.py --env-file .env`；该检查只输出缺失/不匹配的变量名，不会打印密钥。检查通过后启动：`docker compose --profile public up -d --build`。`/health/ready` 返回 503 时 API/gateway 容器会被标为 unhealthy，autoheal 会重启带 `autoheal=true` 标签的容器；服务恢复/降级状态写入日志，并通过 webhook 告警。
5. 用所有者微信打开小程序。客户端调用 `wx.login`，服务端执行 `code2session` 并与 `OWNER_OPENID` 比较；非所有者无法取得访问令牌。后续请求令牌有效期 12 小时，过期前自动刷新。

不要将 `OWNER_OPENID`、AppSecret、Tunnel token、令牌签名密钥或告警 webhook 写入代码、PR、截图或小程序包。autoheal 需要读取 Docker socket 才能重启容器，因此只应在可信的单机部署中启用。

## 临时体验版预览（不等同于 P0 自用鉴权完成）

如果需要先在微信体验版检查界面和功能，可显式启用旧体验凭证兼容模式：服务器 `.env` 保留 `TRIAL_ACCESS_KEY` 并设置 `LEGACY_TRIAL_AUTH_ENABLED=true`；本机被 Git 忽略的 `miniprogram/config.private.js` 设置同一个 `apiBaseUrl`、`authMode: "trial"` 和 `trialAccessKey`，然后运行 `python scripts/preflight_public_deploy.py --legacy-trial-preview`。该模式可继续使用现有 HTTPS 体验隧道，但共享凭证会随体验版小程序包发给体验成员，不能证明调用者是所有者，也不能视为 OpenID 安全 P0 已完成。只用于受控体验名单；切换到正式自用鉴权前必须改回默认 `authMode: "wechat"`、移除客户端体验凭证并配置微信 AppSecret/所有者 OpenID/令牌密钥。
