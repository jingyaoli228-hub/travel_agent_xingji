# 上线检查清单

## 安全与网络

- [ ] `.env` 权限为 600，所有 `change_me` 已替换。
- [ ] `.env`、`runtime/`、`backups/` 未提交 Git。
- [ ] 腾讯云只放行 22/80/443；5432/6379/8000/Chroma 未放行。
- [ ] Google 服务端 Key 限制服务器 IP/API；浏览器 Key 限制域名/API。
- [ ] `CORS_ORIGINS` 是实际域名，不是 `*`。
- [ ] 域名 HTTPS 证书有效，或明确仍处于 IP/HTTP 验证阶段。

## 数据迁移

- [ ] 本地源数据已有不可变备份及 SHA-256 清单。
- [ ] Chroma 源/目标均为 1.5.9。
- [ ] 三个集合数量至少为 307/4/8，维度均为 384，embedding 配置为 ONNX MiniLM。
- [ ] JSON/JSONL 导入脚本重复运行后行数不重复增长。
- [ ] 未重新计算或静默切换 embedding。

## 服务

- [ ] `docker compose config` 成功。
- [ ] 所有服务 `Up`/healthy，API readiness 的 PostgreSQL、Redis、Chroma 都是 `ok`。
- [ ] API 一个 worker，无 `--reload`；RQ Worker 数量为 1。
- [ ] PostgreSQL、Redis、Chroma 没有宿主机端口映射。
- [ ] 日志轮转生效，磁盘余量和 inode 正常。

## 业务验收

- [ ] 完整多轮对话通过。
- [ ] RAG 能命中已迁移攻略，来源不是伪造结果。
- [ ] 调研进度从 queued/running 到 done 或明确 error。
- [ ] 候选选择后能生成完整每日行程。
- [ ] 重启 API 后 `/api/session/{id}` 与 Workspace 仍存在。
- [ ] 重启 Worker 后任务有限重试/明确失败，不永久 running。
- [ ] 同一个 Workspace `request_id` 不造成重复写入；过期 `plan_version` 返回 409。
- [ ] Agent Reach/OpenCLI 缺失时前端显示工具不可用，不显示伪造成功。

## 微信小程序

- [ ] `miniprogram/config.js` 使用正式 HTTPS API 域名，不是 localhost 或占位域名。
- [ ] 微信公众平台已配置 request 合法域名，开发者工具开启域名校验后仍能请求。
- [ ] 已替换正式 AppID，并在真机完成需求确认、调研轮询、候选与逐日行程验证。
- [ ] 后端已接入微信登录并从可信身份推导 `user_id`，客户端不能任意读取他人 session。
- [ ] API 公网开放前已完成身份认证、资源所有权校验、限流与日志脱敏。

## 资源与恢复

- [ ] 完整规划期间 `docker stats --no-stream` 已记录，未发生 OOM。
- [ ] Worker 峰值低于 1.4 GB，整机有至少约 400–500 MB 余量。
- [ ] 已在异机保存一次备份。
- [ ] 已在测试目录/测试机执行过恢复并验证已知 session 与 Chroma 集合。
