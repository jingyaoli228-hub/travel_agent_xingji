# 腾讯云轻量服务器部署手册（4 核 / 4 GB）

本手册对应仓库当前代码。部署形态为一个 FastAPI 进程、一个单并发 RQ Worker、PostgreSQL、Redis、Chroma 和 Caddy。PostgreSQL、Redis、Chroma 均不映射宿主机端口。当前 Caddy 也只绑定服务器回环地址 `127.0.0.1:8080`，通过 SSH 隧道验证；完成身份认证和资源所有权校验前不得公开 80/443。

## 1. 代码审计结论

### 启动入口与依赖

- FastAPI 入口：`travel_agent.main:app`。生产命令固定为一个 Uvicorn worker，不使用 `--reload`。
- 原始依赖见 `requirements.txt`。本次固定了本机已使用的核心版本：LangGraph 1.2.9、Chroma 1.5.9、FastAPI 0.139.2，并增加 `langgraph-checkpoint-postgres`、`psycopg` 和唯一的任务队列 RQ。
- 根目录 `main.py` 是交互式 CLI，不是 Web 服务入口。

### 原有易失状态（现已改造）

| 状态 | 原实现 | 生产实现 |
|---|---|---|
| LangGraph checkpoint | `MemorySaver`，进程重启丢失 | PostgreSQL `PostgresSaver` |
| 调研后台任务 | daemon thread + `_jobs` 字典 | Redis/RQ 队列 + PostgreSQL `task_runs` |
| Workspace | `_states` 字典 | PostgreSQL `workspace_states` JSONB |
| plan_version | 仅 Python 锁 | PostgreSQL compare-and-swap 乐观锁 |
| L0/L1 会话/工作记忆 | Redis；连接失败回退内存 | 生产模式连接失败直接启动失败 |
| 工具缓存/熔断指标 | 进程内缓存 | 仍是可丢失缓存；不作为业务事实来源 |

RQ 只保证任务排队和有限重试，不会从 Python 函数执行到一半的位置继续。Worker 中断后，本次实现从最新 LangGraph checkpoint 重新执行尚未完成的节点；任务最多自动重试两次。超过超时或失联窗口后，PostgreSQL 状态会改为 `error`，不会永久显示 `running`。自动重试耗尽后不会自动无限重建任务；用户再发送一条消息会被视为一次明确的人工重试，并从该 checkpoint 重新提交。

### RAG / Chroma

- 本机实际 Chroma 版本：1.5.9。
- 路径：`./data/chroma`。
- 集合与审计时数量：`travel_guides` 307、`episodic_memory` 4、`user_profile` 8。
- 三个集合均为 384 维，embedding 配置均为 `onnx_mini_lm_l6_v2`（all-MiniLM-L6-v2）。
- 模型由 Chroma ONNX Runtime 使用；项目没有本地 LLM，也未安装 Torch/Transformers。本机缓存审计为 174,510,889 字节，其中压缩包约 83 MB、`model.onnx` 约 90 MB。缓存挂载在 `model_cache` 卷，API 和 Worker 共用，避免重复下载；两个进程仍可能各自创建 ONNX Runtime 会话，所以实际常驻内存必须以上云后的 `docker stats` 为准。
- 迁移脚本复制既有 embedding，不调用收费 API、不重新计算向量，并记录集合配置、数量和维度。

### 本地文件与电脑依赖

- `data/user_profiles.json`：长期用户画像。
- `data/episodic_memory.jsonl`：旅行历史 ledger。
- `data/chroma/`：向量数据。
- `scripts/.xhs_bali_cache.jsonl` 和 `bali_xhs_notes_batch2.md` 是采集/素材文件，不是在线业务状态。
- 应用代码没有写死 `D:\...` 等 Windows 绝对路径；配置路径原本都是相对路径。
- Agent Reach 和 `opencli xiaohongshu` 都通过 subprocess 调本机 CLI。
- OpenCLI 依赖本机 Chrome 登录态。基础云镜像没有 Chrome、OpenCLI 或该登录态，因此小红书实时搜索会明确返回工具不可用，不能伪造成功。既有已入库资料仍可通过 RAG 使用。
- `config/mcporter.json` 的 Exa MCP 地址目前没有被 FastAPI 直接作为 HTTP 客户端调用；实际通路仍是 `AGENT_REACH_SEARCH_CMD`。
- 签证工具仍引用 mock 数据地址，不能视为真实生产数据。

可迁移选择：Agent Reach 若提供纯 Linux CLI 和无浏览器认证，可安装到自定义镜像；OpenCLI 可另建带 Chromium 与持久 profile 的受控容器，但存在账号风控、验证码和资源开销，当前 4 GB 主机不建议与主服务混跑。低成本阶段应依赖 Google Places/Weather、模型联网能力和已入库 RAG，并向用户显示小红书通路不可用。

## 2. 空白 Ubuntu 安装 Docker

以下命令适用于 Ubuntu 22.04/24.04：

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
newgrp docker
docker version
docker compose version
```

本阶段腾讯云防火墙只放行 SSH 22。不要放行 80、443、5432、6379、8000、8080 或 Chroma 端口。

## 3. 上传并配置

把整个项目上传到服务器，例如 `/opt/travel-agent`。不要上传本机 `.env`；单独通过安全方式填写服务器密钥。

```bash
cd /opt/travel-agent
cp .env.example .env
chmod 600 .env
nano .env
sh scripts/server_prepare.sh
```

必须修改：

1. `POSTGRES_PASSWORD`，以及 `DATABASE_URL` 中同一个密码。若密码含 `@:/?#` 等字符，要 URL encode。
2. 至少一个模型 Key。
3. `GOOGLE_MAPS_API`；地图页面需要时再填浏览器 Key。
4. 隧道验证阶段保持 `DOMAIN=:80`，并使用 `CORS_ORIGINS=http://localhost:8080,http://127.0.0.1:8080`。
5. 不要在当前版本直接配置公网域名：应用尚无身份认证，且服务端尚未从可信身份推导 `user_id`。

构建镜像：

```bash
docker compose config
docker compose build
docker compose up -d postgres redis chroma
docker compose ps
```

## 4. 迁移现有数据（不修改源目录）

确保上传的 `data/` 是迁移前备份副本。本机原始数据已另存到 `backups/pre-cloud-20261017-153000` 并带 SHA-256 清单。

先复制现有 Chroma embedding：

```bash
docker compose run --rm api python scripts/migrate_chroma.py \
  --source /legacy-data/chroma --host chroma --port 8000 \
  --manifest /app/chroma-migration-manifest.json
```

命令会输出每个集合的源/目标数量和 384 维验证。它使用 upsert，可重复执行，不删除目标数据。

再导入 JSON/JSONL：

```bash
docker compose run --rm api python scripts/import_legacy_state.py \
  --profiles /legacy-data/user_profiles.json \
  --episodes /legacy-data/episodic_memory.jsonl
```

画像按 `user_id` upsert；旅行历史按内容 SHA-256 去重，因此脚本可重复执行。源文件保持只读挂载。

## 5. 启动与验证

```bash
docker compose up -d
docker compose ps
docker compose logs --tail=100 api worker chroma
curl -fsS http://127.0.0.1/health
curl -fsS http://127.0.0.1/health/ready
```

发起最小对话：

```bash
curl -sS http://127.0.0.1/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"cloud-smoke-1","user_id":"cloud-user-1","message":"我想去东京旅行3天"}'
```

在本地 Windows PowerShell 另开窗口建立隧道：

```powershell
ssh -i "$env:USERPROFILE\.ssh\tencent_travel_agent" -N -L 8080:127.0.0.1:8080 ubuntu@SERVER_IP
```

浏览器打开 `http://localhost:8080`，完成需求确认、调研、候选选择和行程生成。然后执行持久性验收：

```bash
docker compose restart api
curl -sS http://127.0.0.1/api/session/cloud-smoke-1
```

Worker 恢复验收应使用新的测试会话：在状态为 `running` 时执行 `docker compose kill worker`，等待超过 worker 失联窗口或重新启动 Worker：

```bash
docker compose up -d worker
docker compose logs -f --tail=100 worker
curl -sS 'http://127.0.0.1/api/research/status?session_id=测试会话ID'
```

预期是 RQ 有限重试并从最新 checkpoint 重跑当前节点，或最终明确 `error`；不能长期保持 `running`。任务的外部 API 调用可能重复，所以工具写操作必须继续保持幂等。本项目当前调研工具主要是读取操作，Workspace 写入另有 `request_id` 和 `plan_version` 保护。

## 6. 4 GB 内存预算

Compose 上限：API 768 MB、Worker 1400 MB、PostgreSQL 512 MB、Chroma 640 MB、Redis 160 MB、Caddy 96 MB，总上限约 3.5 GB，给内核和 Docker 留约 0.5 GB。Worker 并发固定为 1；Uvicorn 固定一个进程；PostgreSQL shared_buffers 为 128 MB；Redis 最大内存 128 MB 且 `noeviction`，避免悄悄丢队列任务。

部署后用真实流量记录实际值：

```bash
docker stats --no-stream
docker compose exec postgres psql -U travel_agent -d travel_agent -c "select count(*) from task_runs;"
docker compose exec redis redis-cli info memory | grep used_memory_human
```

如果 Worker 接近 1.4 GB，先减少调研内部 ThreadPool 并行度或降低候选规模，不要增加 Worker 数量。不要在这台机器再部署浏览器自动化。若系统发生 OOM，用 `dmesg -T | grep -i -E 'oom|killed process'` 核对，而不是直接扩大重试次数。

## 7. 备份与异机恢复

```bash
sh scripts/backup.sh
```

脚本短暂停止 Worker、Redis、Chroma，使用 `pg_dump` 备份数据库并打包 Chroma/Redis 文件，随后自动恢复服务。把生成的 `backups/server-*` 目录复制到另一台机器或对象存储；仅留在同一块云盘不算备份。`.env` 含密钥，不进入备份包，应单独加密保管。

在一台空白实例上恢复，先确保 `runtime/chroma`、`runtime/redis` 为空：

```bash
CONFIRM_RESTORE=YES sh scripts/restore.sh /path/to/server-backup
```

恢复脚本会拒绝覆盖非空 Chroma/Redis 目录。恢复后必须检查 readiness、已知 session、Chroma 集合数量和一次完整 RAG 查询。

