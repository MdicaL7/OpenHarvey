# OpenHarvey + Agent Memory + Langfuse：新电脑本地部署交接手册

更新：2026-10-19。交接对象：在另一台电脑上执行部署的 AI。

> **目标环境更新：用户已确认目标电脑只能运行原生 Windows，不能使用 Docker、WSL2 或虚拟机，且所有服务必须同机。因此本篇 Docker/POSIX 配方不适用于该目标电脑，不要执行。** 当前源码尚未完成原生 Windows 适配。请先阅读 [原生 Windows 可行性与适配交接](windows-native-feasibility.zh-CN.md)；该文档说明待开发项和 Langfuse 的版本取舍，并非已验证的安装手册。

目标是**全新初始化**，不迁移任何旧账号、合同、记忆、数据库、密钥或测试身份。部署 OpenHarvey、本地 OpenCode、MemoryCore、MemoryProxy、Memory Hub 和官方 Langfuse。业务和记忆模型使用 OpenAI Chat Completions 兼容 API。无需 Railway、Vercel、E2B、Supabase、ChatGPT 订阅桥接或旧实验的 8766/8767 服务。

本手册基于源码、当前部署配置和官方 Langfuse Compose 核对编写；没有在目标电脑完成空环境验收。执行 AI 必须完成末尾验收，记录实际失败，不能把健康检查或历史实验结果当作部署成功。

## 1. 使用指定仓库与版本

| 项目 | 仓库 | 分支/版本 |
|---|---|---|
| OpenHarvey | https://github.com/MdicaL7/OpenHarvey.git | `refactor/contract-memory-decouple`；业务源码基线 `536395b`，本手册及后续文档提交在该分支 |
| Agent Memory | https://github.com/MdicaL7/TencentDB-Agent-Memory-contract.git | `feat/contract-prompt-mode`；提交 `ea7d3cb` |
| Langfuse | https://github.com/langfuse/langfuse.git | tag `v3.179.1`，Git SHA `3cb6514396f788f06199794dbdc09d8925d2cf70` |
| OpenCode | npm `opencode-ai` | `1.16.2` |

不要使用两个项目的默认 `main`，也不要使用上游 `agentmemory/*:latest` 代替当前修复版。Agent Memory 三个镜像从上述 fork 源码构建。Langfuse 官方当前 main 已升级 v4，本手册固定到已有集成验证记录的 v3；同时固定 Web/Worker 镜像，不能仅固定 Git tag 而保留镜像 `:3` 漂移。

不依赖旧 `docs/contract-memory-v2-deployment.md` 中的启动命令：该文档属于旧实验，引用的 `deploy/contract-memory/manage.py` 已不在当前源码中。旧 `run_tencentdb_local.py` 也含旧机器默认路径和 `deepseek-flash` 初始化值，本手册用显式初始化代替。

## 2. 目标电脑预检

需要 Git、Docker Engine + Compose v2（macOS/Windows 可用 Docker Desktop）、Python 3.12、Node.js 22、npm、curl、rsync、Bash。

- Windows 在 **WSL2 Linux 环境**运行 Python、Node、代码和命令；当前程序使用 `fcntl` 等 POSIX 接口，不按原生 Windows Python 部署。源码与数据放 WSL Linux 文件系统。
- Docker 必须运行 Linux 容器；根据 `docker info --format '{{.Architecture}}'` 选择 `linux/arm64` 或 `linux/amd64`，不盲目复制另一台机器的镜像。
- 检查 8081、8430、8106、8125、8424、3000、3030、9090、9091、5432、6379、8123、9000 的占用。冲突时只改本套部署的映射及引用，不停止不相关服务。
- Langfuse 官方 VM 指南建议至少 4 核/16 GiB；这不是整套系统的实测最低值。额外给镜像构建、OpenCode、记忆服务留资源，检查 Docker Desktop 的内存/磁盘分配。
- 模型必须支持 `/chat/completions`、工具调用和所需的流式响应。记忆提炼还需稳定输出结构化结果。模型可相同，也可业务/记忆分开。

先向用户收集：两组模型 Base URL、API Key、model ID、真实上下文/输出上限；新管理员用户名/密码。密钥通过目标电脑私有文件或交互输入提供，不写到聊天、仓库或命令历史。若同一模型复用，只需用户提供一次。

## 3. 目录与代码

以下命令以 Bash 为例，所有终端都使用同一组路径：

```bash
export OH_STACK_ROOT="$HOME/openharvey-local"
export OH_STATE="$OH_STACK_ROOT/state"
umask 077
mkdir -p "$OH_STACK_ROOT" "$OH_STATE/config" "$OH_STATE/logs" "$OH_STATE/openharvey"
cd "$OH_STACK_ROOT"
git clone --branch refactor/contract-memory-decouple https://github.com/MdicaL7/OpenHarvey.git
git clone --branch feat/contract-prompt-mode https://github.com/MdicaL7/TencentDB-Agent-Memory-contract.git AgentMemory
git clone --branch v3.179.1 --depth 1 https://github.com/langfuse/langfuse.git Langfuse
git -C OpenHarvey rev-parse HEAD
git -C AgentMemory rev-parse HEAD
git -C Langfuse rev-parse HEAD
```

已有同名目录时检查其来源和本地修改，不覆盖。记录完整 SHA 到私有部署记录。全程不复制源电脑的 `.env`、`state`、`login.json`、`.admin-key`、`control.key` 或任何数据卷。

## 4. 部署官方 Langfuse

在 `Langfuse` 目录使用官方 `docker-compose.yml`。按照 [官方 Compose 文档](https://langfuse.com/self-hosting/deployment/docker-compose)初始化密钥，并核对 [本手册固定版本的 Compose](https://github.com/langfuse/langfuse/blob/v3.179.1/docker-compose.yml)。

1. 将 Web 和 Worker 的镜像分别固定为 `langfuse/langfuse:3.179.1`、`langfuse/langfuse-worker:3.179.1`。先验证目标架构可拉取；失败时报告，不静默换 v4。
2. 在私有 `.env` 中为 PostgreSQL、ClickHouse、Redis、MinIO、`NEXTAUTH_SECRET`、`SALT`、`ENCRYPTION_KEY` 生成新值；`ENCRYPTION_KEY` 为 32 字节 hex。`DATABASE_URL` 与 PostgreSQL 密码一致；所有 S3 event/media/batch secret 与 MinIO 凭据一致。可用 URL 安全的随机 hex 密码，避免 URL 转义问题。
3. 本机使用 `NEXTAUTH_URL=http://localhost:3000`，媒体上传地址为 `http://localhost:9090`。将官方 Compose 的 Web/MinIO 对外端口改成 `127.0.0.1:3000:3000` 和 `127.0.0.1:9090:9000`；其余保持官方回环绑定。若已占端口，成对调整引用。
4. 创建共享观测网络，并为 Langfuse Web 加入该网络。这样 Memory 容器通过网络别名访问 Langfuse，兼容 Linux 宿主机的回环绑定，也满足当前追踪代码对本地地址的限制。

```bash
docker network inspect oh-observability >/dev/null 2>&1 || docker network create oh-observability
```

在 `Langfuse/docker-compose.override.yml` 保存：

```yaml
services:
  langfuse-web:
    networks:
      default: {}
      observability:
        aliases: [host.docker.internal]
networks:
  observability:
    external: true
    name: oh-observability
```

这里 `host.docker.internal` 是该专用 Docker 网络上 Langfuse Web 的别名。不要在下文 Memory 容器中再给这个名字添加 `extra_hosts`，否则会覆盖此路由。若模型服务也在宿主机，请另设不同的模型主机名/路由，不复用这个名字。

```bash
cd "$OH_STACK_ROOT/Langfuse"
docker compose config --quiet
docker compose up -d
docker compose ps
curl -fsS http://localhost:3000/api/public/health
```

访问 UI，新建本地用户、组织和项目 `OpenHarvey Local`，创建项目 Public Key/Secret Key；也可以按官方 headless initialization 配置。将密钥存入 `$OH_STATE/config/langfuse-python.json`：

```json
{"host":"http://127.0.0.1:3000","public_key":"REPLACE_PUBLIC_KEY","secret_key":"REPLACE_SECRET_KEY"}
```

再创建私有 `$OH_STATE/config/langfuse.env`，供 Memory Compose 使用：

```dotenv
LANGFUSE_ENABLED=true
LANGFUSE_HOST=http://host.docker.internal:3000
LANGFUSE_PUBLIC_KEY=REPLACE_PUBLIC_KEY
LANGFUSE_SECRET_KEY=REPLACE_SECRET_KEY
```

两份配置使用同一个 Langfuse 项目。文件权限 0600。不要把完整 `docker compose config` 的展开输出贴到报告，它可能包含密钥。

Langfuse 会启动 Web、Worker、PostgreSQL、ClickHouse、Redis、MinIO 六个服务。无需再分别 clone 这四个基础设施。首次拉取后记录各镜像 digest；官方辅助镜像的浮动标签也应在目标机器验收后固定。

## 5. 构建 Agent Memory

```bash
cd "$OH_STACK_ROOT/AgentMemory"
docker build -t oh-local/memory-core:ea7d3cb MemoryCore
docker build -t oh-local/memory-proxy:ea7d3cb MemoryProxy
# 按目标 Docker 架构二选一设置，不同时执行两行：
export OH_DOCKER_PLATFORM=linux/arm64
# export OH_DOCKER_PLATFORM=linux/amd64
CTX_DIR="$OH_STATE/hub-build-context" \
  PLATFORM="$OH_DOCKER_PLATFORM" IMAGE_NAME=oh-local/memory-hub IMAGE_TAG=ea7d3cb \
  bash deploy/panel-knowledge-combined/build.sh
```

Hub 构建脚本会重建 `CTX_DIR`，必须使用本套部署专用目录。默认平台是 amd64，因此 ARM 电脑必须显式传平台。构建失败保留相关日志，不改用未包含本地修复的公共 latest。

## 6. 新建 Memory 配置

所有下列配置保存在 `$OH_STATE/config`，不放 Git。示例中的占位值必须替换。用 YAML/JSON 序列化库写入凭据，避免用 shell 文本替换破坏特殊字符。

`core.yaml`：

```yaml
deployMode: standalone
stateBackend: local
server: {host: 0.0.0.0, port: 8420}
data: {baseDir: /data/tdai-memory}
llm:
  provider: openai
  baseUrl: "REPLACE_MEMORY_BASE_URL"
  apiKey: "REPLACE_MEMORY_API_KEY"
  model: "REPLACE_MEMORY_MODEL"
  maxTokens: 8192
  timeoutMs: 300000
memory:
  promptMode: code
  capture: {enabled: true}
  extraction: {enabled: true, enableDedup: true, maxMemoriesPerSession: 20}
  persona: {triggerEveryN: 50, maxScenes: 15}
  pipeline:
    everyNConversations: 5
    enableWarmup: true
    l1IdleTimeoutSeconds: 600
    l2DelayAfterL1Seconds: 90
    l2MinIntervalSeconds: 900
    l2MaxIntervalSeconds: 3600
  recall: {enabled: true, maxResults: 5, scoreThreshold: 0.3, strategy: hybrid, timeoutMs: 5000}
  storeBackend: sqlite
  embedding: {provider: none}
skill:
  enabled: true
  routing: {mode: bm25, searchTopK: 20}
  extraction: {enabled: false}
observability:
  langfuse: {enabled: true}
```

`maxTokens` 按所选模型真实限制填写；仅接受流式的供应商需根据 `MemoryCore/src/gateway/config.ts` 使用 `llm.stream: true`。全局 `promptMode: code` 是默认族，OpenHarvey 创建 Agent 时通过 metadata 显式选择 `contract`，不要把全局配置误当作合同 Agent 未启用。此部署用 OpenHarvey 自带合同 Skills，不自动提取 Skill。Embedding 默认关闭，使用现有关键词检索；如启用，需要单独 `/embeddings` 模型和维度。

`proxy.yaml`：

```yaml
server: {host: 0.0.0.0, port: 8096, forwardTimeoutMs: 600000}
upstream:
  url: "REPLACE_BUSINESS_BASE_URL/chat/completions"
  apiKey: "REPLACE_BUSINESS_API_KEY"
log: {file: "", level: info, backend: console}
tdai:
  enabled: true
  endpoint: http://memory-core:8420
  apiKey: local
  serviceId: default
  memory: {enabled: true, inject: true, writeL0: true, recallL1: true, injectL2L3: true}
skill: {endpoint: "http://memory-core:8420", serviceToken: local}
auth: {enabled: true, url: "http://memory-core:8420", timeoutMs: 5000}
sessionInit:
  enabled: true
  maxRetries: 3
  injectAgentContext: true
  injectTaskContext: true
  headerAutoSelect:
    enabled: true
    teamHeader: x-team-id
    agentHeader: x-agent-id
    taskHeader: x-task-id
    onMismatch: form
costGuard: {enabled: false}
injection:
  enabled: true
  externalGatewayUrl: http://127.0.0.1:8106
  injectors: [tdai-memory]
extraction: {enabled: true, extractors: [tdai-memory]}
redis: {enabled: false}
storage:
  enabled: true
  backend: sqlite
  sqlite: {dbPath: /data/tdai-memory-proxy/cache.sqlite}
creditReport: {enabled: false, url: "", timeoutMs: 5000}
langfuse: {enabled: true, debug: false, maxQueueSize: 256, flushAt: 32, flushInterval: 1}
```

注意 base URL 若已带 `/chat/completions`，不要重复追加。Proxy 的上游 API Key 与用户登录 Memory 的 User Key 完全不同。`local` 是部分内部客户端使用的占位值，不是模型密钥。当前 Proxy 的 `auth/verify` 请求不发送 gateway Bearer，因此下文 Core 的全局 Bearer gate 保持空值；用户身份验证仍开启。此配方只适用于本机回环端口和专用 Docker 网络，不能直接暴露到公网。

`hub.env`：

```dotenv
KNOWLEDGE_SERVICE_KEY=REPLACE_NEW_RANDOM_SERVICE_KEY
KNOWLEDGE_AUTH_TOKEN=REPLACE_SAME_SERVICE_KEY
LLM_MODE=custom
LLM_PROTOCOL=openai
LLM_BASE_URL=REPLACE_MEMORY_BASE_URL
LLM_API_KEY=REPLACE_MEMORY_API_KEY
LLM_MODEL=REPLACE_MEMORY_MODEL
KNOWLEDGE_LLM_BINDING_SYNC=0
```

暂时不创建或挂载 `memory-trace.json`，等新用户/团队/Agent 初始化后再启用身份范围追踪。否则占位 ID 会导致没有 trace。

## 7. 启动 Memory 三件套

在 `$OH_STATE/compose.memory.yaml` 保存：

```yaml
name: oh-local-memory
services:
  memory-core:
    image: oh-local/memory-core:ea7d3cb
    restart: unless-stopped
    ports: ["127.0.0.1:8430:8420"]
    environment:
      TDAI_GATEWAY_CONFIG: /data/config/tdai-gateway.yaml
      TDAI_GATEWAY_API_KEY: ""
      TDAI_DATA_DIR: /data/tdai-memory
      STORE_MODE: sqlite
      TDAI_METADATA_BACKEND: sqlite
      TDAI_RUNTIME_REVISION: ea7d3cb
    env_file: [./config/langfuse.env]
    volumes:
      - core-data:/data/tdai-memory
      - ./config/core.yaml:/data/config/tdai-gateway.yaml:ro
    networks: [default, observability]
  memory-hub:
    image: oh-local/memory-hub:ea7d3cb
    restart: unless-stopped
    depends_on:
      memory-core: {condition: service_healthy}
    ports: ["127.0.0.1:8125:8125", "127.0.0.1:8424:8424"]
    environment:
      PANEL_PORT: "8125"
      KNOWLEDGE_PORT: "8424"
      KNOWLEDGE_PUBLIC_BASE_URL: http://127.0.0.1:8424/v3
      REMOTE_INSTANCE_ID: default
      REMOTE_INSTANCE_NAME: OpenHarvey Local
      REMOTE_INSTANCE_URL: http://memory-core:8420
      REMOTE_INSTANCE_KEY: local
      REMOTE_INSTANCE_PROXY_URL: http://127.0.0.1:8106
    env_file: [./config/hub.env]
    volumes: [hub-data:/data/knowledge]
    networks: [default]
  memory-proxy:
    image: oh-local/memory-proxy:ea7d3cb
    restart: unless-stopped
    depends_on:
      memory-core: {condition: service_healthy}
    ports: ["127.0.0.1:8106:8096"]
    environment:
      PROXY_DB_PATH: /data/tdai-memory-proxy/proxy.db
      TDAI_RUNTIME_REVISION: ea7d3cb
    env_file: [./config/langfuse.env]
    volumes:
      - proxy-data:/data/tdai-memory-proxy
      - ./config/proxy.yaml:/data/config.yaml:ro
    networks: [default, observability]
networks:
  observability:
    external: true
    name: oh-observability
volumes:
  core-data: {}
  proxy-data: {}
  hub-data: {}
```

```bash
cd "$OH_STATE"
docker compose -f compose.memory.yaml config --quiet
docker compose -f compose.memory.yaml up -d
docker compose -f compose.memory.yaml ps
curl -fsS http://127.0.0.1:8430/health
curl -fsS http://127.0.0.1:8106/health
curl -fsS http://127.0.0.1:8424/health
```

访问 `http://127.0.0.1:8125` 核对 Hub 页面。不要另外运行 `deploy/global-images/start-all.sh`：它会生成另一套容器和配置，且不能自动套用本手册的追踪、存储和模型设置。

## 8. 安装 OpenHarvey 与隔离 OpenCode

```bash
cd "$OH_STACK_ROOT/OpenHarvey"
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci
npm run build:memory
npm run build:redline
npm install --prefix "$OH_STATE/opencode" opencode-ai@1.16.2
export PATH="$OH_STATE/opencode/node_modules/.bin:$PATH"
opencode --version
export CW_DATA_DIR="$OH_STATE/openharvey"
export CW_SANDBOX_BACKEND=local
export CW_PUBLIC_ORIGIN=http://127.0.0.1:8081
export CW_SECURE_COOKIE=0
export CW_LOCAL_DEV_USER=
export CW_TDAI_ADMIN_KEY_FILE="$OH_STATE/config/admin.key"
# 当前标准原生 API 使用 local gateway；不需要旧合同控制密钥文件。
unset CW_TDAI_CONTROL_KEY_FILE
```

将这些不含密钥的环境配置保存为私有启动脚本，之后初始化、Web 和进程管理器统一加载。不要使用旧机器的路径，也不修改用户的全局 OpenCode 配置。

## 9. 初始化全新账号与实际模型

先在 `$OH_STATE/config/business-model.json` 写入实际模型描述（不含模型 API Key，真实 Key 只在 Proxy 中）：

```json
{"id":"REPLACE_BUSINESS_MODEL","context":128000,"output":8192,"native":{"tool_call":true}}
```

两个数字必须匹配供应商限制。`native` 和额外推理参数按模型需要设置，不给所有供应商强加 DeepSeek 的 `thinking` 参数。

在 OpenHarvey 仓库目录执行下面的一次性初始化。它会要求输入新密码、创建新 Memory 管理员和业务身份、将默认硬编码模型替换为实际业务模型，并通过原生 OpenCode 发起小型连通性测试。这个测试会产生少量模型调用。

```python
# 将本段保存为 $OH_STATE/bootstrap.py，随后在 OpenHarvey 根目录运行：
# PYTHONPATH=. .venv/bin/python "$OH_STATE/bootstrap.py"
import asyncio, getpass, json, os, secrets
from pathlib import Path
import httpx
from contract_web.app import create_app

base = Path(os.environ['OH_STATE'])
os.umask(0o077)
adminfile = base / 'config/admin.key'
if not adminfile.exists():
    adminfile.write_text('sk-mem-' + secrets.token_hex(24))
    adminfile.chmod(0o600)
admin_key = adminfile.read_text().strip()
headers = {'Authorization': 'Bearer local', 'x-tdai-service-id': 'default'}
with httpx.Client(timeout=15, trust_env=False) as c:
    r = c.post('http://127.0.0.1:8430/v3/internal/meta/user/init-admin',
               headers=headers, json={'username': 'admin', 'user_key': admin_key})
    if r.status_code not in (200, 409):
        raise RuntimeError(f'init-admin HTTP {r.status_code}; inspect privately')
    r = c.post('http://127.0.0.1:8430/v3/meta/auth/verify', headers=headers,
               json={'user_key': admin_key})
    r.raise_for_status()
    payload = r.json()
    assert payload.get('data', payload).get('valid') is True, 'Admin key does not match this volume'

app = create_app()
s, models, tdai, manager = app.state.store, app.state.models, app.state.tdai, app.state.manager
username = 'admin'  # 如用户指定其他用户名，在首次运行前修改。
u = s.one('SELECT * FROM users WHERE username=?', (username,))
if not u:
    uid = s.add_user(username, getpass.getpass('新 OpenHarvey 密码（至少 8 位）: '))
    s.execute("UPDATE users SET role='admin' WHERE id=?", (uid,))
u = s.one('SELECT * FROM users WHERE username=?', (username,))
assert u['active'] and u['role'] == 'admin'
from contract_web.contract_memory import ContractMemory

async def initialize():
    if not s.one('SELECT 1 FROM tdai_users WHERE user_id=?', (u['id'],)):
        await tdai.connect(u, admin_key=admin_key, core_url='http://127.0.0.1:8430',
            proxy_url='http://127.0.0.1:8106/opencode/default/v1',
            username='openharvey-admin', gateway_key='local')
    await ContractMemory(s, models, tdai).upgrade(u)
    spec = json.loads((base/'config/business-model.json').read_text())
    assert spec['id'] and not spec['id'].startswith('REPLACE_')
    p = s.one("SELECT * FROM providers WHERE org_id=? AND id='tencentdb-memory'", (models.scope(u),))
    saved = models.save(u, {'id':'tencentdb-memory', 'label':'本地 Agent Memory',
        'base_url':p['base_url'], 'protocol':'openai', 'revision':p['revision'],
        'extra_body':{}, 'models':[{'id':spec['id'], 'label':spec['id'],
            'context':spec['context'], 'output':spec['output'], 'native':spec.get('native',{})}]})
    # 不传 key，保留原加密的 Memory User Key；不能填上游模型 API Key。
    s.execute('UPDATE users SET model=? WHERE id=?', ('tencentdb-memory/'+spec['id'], u['id']))
    result = await manager.apply_personal(u, saved['revision'])
    if not result.get('applied'):
        raise RuntimeError('Model configuration was not applied')
    team = s.one('SELECT * FROM teams WHERE owner_id=?', (u['id'],))
    identity = s.one('SELECT * FROM memory_identities WHERE user_id=?', (u['id'],))
    scope = {'app_user_id':u['id'], 'instanceId':'default',
        'teamId':team['tdai_team_id'], 'agentId':team['agent_id'], 'userId':identity['tdai_user_id']}
    (base/'config/new-identity.json').write_text(json.dumps(scope, indent=2))
    (base/'config/memory-user.key').write_text(models.decrypt(identity['secret']))
    print('初始化与原生模型连通性测试成功；身份和 Hub 登录 key 已保存在私有 config 目录。')
asyncio.run(initialize())
```

这是可复用初始化：已存在的用户/团队不重复创建；每次执行仍会重新保存模型配置并做真实连通性测试。普通启动不要反复执行它。若半途失败，保留数据和日志修复，不清空卷掩盖故障。

## 10. 启用三端 Langfuse 追踪

在初始化后读取 `new-identity.json`（不读取/输出密钥），生成 `$OH_STATE/config/memory-trace.json`：

```json
{
  "enabled": true,
  "run_id": "fresh-local-acceptance",
  "test_case_id": "deployment-smoke",
  "include_content": false,
  "synthetic_data": false,
  "app_user_ids": ["REPLACE_APP_USER_ID"],
  "scopes": [{"instanceId":"default","teamId":"REPLACE_TEAM_ID","agentId":"REPLACE_AGENT_ID"}],
  "versions": {"openharvey":"REPLACE_FULL_COMMIT","memory":"REPLACE_FULL_COMMIT"}
}
```

给 Memory Compose 的 `memory-core` 和 `memory-proxy` **分别追加**，保留原挂载和环境：

```yaml
environment:
  MEMORY_TRACE_CONFIG_FILE: /data/memory-trace.json
volumes:
  - ./config/memory-trace.json:/data/memory-trace.json:ro
```

Web 的启动环境追加：

```bash
export MEMORY_TRACE_CONFIG_FILE="$OH_STATE/config/memory-trace.json"
export LANGFUSE_CREDENTIALS_FILE="$OH_STATE/config/langfuse-python.json"
export OH_RUNTIME_REVISION="$(git -C "$OH_STACK_ROOT/OpenHarvey" rev-parse HEAD)"
```

重新创建 Core/Proxy 使挂载与环境生效：

```bash
cd "$OH_STATE"
docker compose -f compose.memory.yaml up -d --force-recreate memory-core memory-proxy
```

追踪配置按进程缓存，修改后要重启相应进程。范围最多 8 组，必须是新建的真实 `instanceId/teamId/agentId`，不能填 `*` 或旧测试 ID。新团队需显式更新范围。该功能当前是按身份选择的追踪，不是全用户自动开启。

默认保留哈希/元数据。若仅对本次虚构验收材料需要全文，再将 `include_content` 和 `synthetic_data` 同时设为 true；真实合同不能假标成 synthetic 绕过内容限制。L1 decisionAudit 是额外可选审计，可按 `MemoryCore/L1_DECISION_AUDIT.md` 显式配置，普通运行不依赖它。

**当前版本的观测限制：**本机新增关联层原先为订阅桥接实验设计，部分 metadata 仍写 `usage_owner=subscription_bridge`、`langfuse.environment=native-test-20261015`；被选中的 Core/Proxy span 会去除 Token/费用以避免重复计数。本手册使用直连 API、不运行订阅桥接，因此不能声称获得了完整 Token/成本账单。用新 `run_id` 和身份筛选验收，Token/成本单列为未覆盖；若需要完整统计，应作为独立适配修复，不能伪造 usage。详见 `docs/langfuse-tracing.md`。

Hub 的知识生成追踪是另一个可选入口；若启用 Wiki/Knowledge 实际模型调用，将 Hub 也加入 `observability` 网络，并按 `MemoryKnowledge/src/telemetry.ts` 配置 `LANGFUSE_BASE_URL`、`LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`。它不是自动并入 OpenHarvey 请求的同一条 trace。

## 11. 启动 Web 并配置可恢复运行

在加载第 8、10 节同一份环境后：

```bash
cd "$OH_STACK_ROOT/OpenHarvey"
.venv/bin/python -m uvicorn contract_web.app:create_app --factory \
  --host 127.0.0.1 --port 8081 --workers 1 --timeout-graceful-shutdown 10
```

访问 `http://127.0.0.1:8081/spaces`，使用新管理员账号密码登录。Hub 使用 `$OH_STATE/config/memory-user.key` 中的新 User Key 登录；不要把供应商 API Key 当成 Hub 登录凭据。

首轮前台验收后，执行 AI 应按目标系统配置后台运行：Linux/WSL 用实际可用的用户服务管理方式（支持 systemd 时可用 user unit）；macOS 用 LaunchAgent。指定绝对工作目录、Python 路径、OpenCode PATH、同一数据目录及环境文件；输出日志到 `$OH_STATE/logs`。只运行一个 Web 实例/worker。记录启动、停止、重启命令，验证关闭终端后服务仍可访问。

Docker 容器使用 `unless-stopped`；系统重启后仍需 Docker 本身启动。OpenCode 由 OpenHarvey RuntimeManager 管理，不额外手动启动第二个相同用户运行时。

## 12. 验收与交付给用户的结果

按顺序验证，使用虚构合同，不导入任何旧电脑数据：

1. 六个 Langfuse 服务和三个 Memory 服务状态正常；Web、Core、Proxy、Knowledge 健康接口返回成功；三个 UI 能打开并登录。
2. OpenHarvey 选中的 provider 为 `tencentdb-memory`，模型 ID 是用户提供的真实值，不残留 `deepseek-flash`。实际对话能返回内容。
3. 上传虚构合同，完成至少一次原文读取/工具调用、可定位引用、生成成果和下载。仅 `Reply OK` 不足以验收工具能力。
4. 保存一次风险处置/经验相关操作；核对 OpenHarvey 投递状态及 Core 的 L0。等待原生后台提炼生成 L1，再在新会话验证召回。L1/L2/L3 有阈值和空闲调度，报告实际等待时长与哪些层已完成；不手写记忆或缩短阈值伪造成功。
5. 在 Langfuse 项目按新 `run_id`/身份查到 OpenHarvey、Proxy、Core 的真实追踪，至少验证一次业务请求和一次后台记忆处理。异步批次不一定属于同一 trace；通过身份和来源 ID 对应。不得只看 UI 首页或 exporter enabled 日志。
6. 重启本套 Web 和 Memory 容器，确认新账号、合同、成果、记忆保留；没有重复实例、重复团队或重建卷。
7. 交付一份脱敏部署记录：系统/架构、完整 Git SHA、镜像 ID/digest、目录、端口、后台服务名、启停命令、配置路径、验收证据及未完成项。登录秘密只留私有本机文件，报告给路径即可。

首次部署可以有未达到 L2/L3 触发阈值的状态，但必须明确列为待验证，不能宣称完整记忆闭环已全部通过。健康检查、源码协议支持、旧电脑曾验证过，均不能替代本机模型验收。

## 13. 常见问题

| 现象 | 检查 |
|---|---|
| clone 后没有最新追踪 | 是否选错 main；核对分支和 SHA |
| 模型不存在/404 | 初始化后是否残留默认 deepseek-flash；URL 是否重复追加路径；服务是否只支持 Responses |
| 对话正常但 L1/L2 失败 | Core 独立模型配置、结构化结果、工具调用、超时、后台调度；业务模型通过不代表记忆模型通过 |
| 没有 Langfuse 数据 | project keys、容器 DNS、三端开关、真实 scope、重启后生效、导出错误；不要放宽身份过滤来伪造成功 |
| Langfuse 有 trace 但无完整 Token | 本版本直连 API 的既有观测限制，见第 10 节 |
| Memory User Key 验证失败 | 新卷和新 admin.key 是否配对；是否把模型 API Key 用成 User Key；是否误开启 Core 全局 Bearer gate 导致当前 Proxy auth 客户端被拒绝 |
| Hub/Proxy 无法连接 Core | Compose 内部使用 memory-core:8420；宿主机使用 127.0.0.1:8430，两者不可混用 |
| 端口冲突 | 调整本套映射及所有引用，不停止无关容器 |
| macOS ARM 构建 Hub 很慢 | 是否忘记显式设置 linux/arm64，导致默认 amd64 仿真 |
| 文件权限错误 | 检查私有配置可被相应容器 UID 读取；只给所需 UID 权限，不将全部秘密改成全局可读 |

停止本套 Memory：`docker compose -f "$OH_STATE/compose.memory.yaml" stop`。Langfuse 在其目录执行 `docker compose stop`。正常维护不执行 `down -v`、volume prune 或旧脚本的 purge。

## 可直接转交给目标电脑 AI 的任务

> 请按本手册部署一套全新的 OpenHarvey + Agent Memory + Langfuse 本地环境。先确认操作系统、架构、依赖、端口和模型配置，使用指定远程分支与版本，不迁移旧数据。将配置、日志、密钥与数据放在独立私有目录。按手册构建镜像、初始化新身份、配置实际 OpenAI 兼容模型、开启范围追踪并完成真实验收。遇到平台差异可做必要的部署适配并记录；不要擅自更换业务版本、删除数据、暴露公网或绕过身份限制。最终提供地址、启停方法、版本、私有凭据文件路径、验收结果和明确的剩余限制。
