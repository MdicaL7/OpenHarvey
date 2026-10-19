# 原生 Windows：可行性与适配交接

核查日期：2026-10-19。状态：**可行性分析，尚未完成原生 Windows 构建、运行或端到端验收。**

## 用户的固定约束

- Windows 原生运行，不使用 Docker、WSL2、Linux 虚拟机。
- 所有应用、数据库和观测服务在同一台电脑，不改为云端或另一台内网主机。
- 全新使用，不迁移旧账号、合同、记忆或凭据。
- 仍需要 Langfuse；不能未经讨论以其他观测产品替代。
- 模型按前述需求使用 OpenAI 兼容 API；“服务同机”不等于新增要求在本机运行模型权重。

之前的 `local-fresh-deployment.zh-CN.md` 基于 Docker/POSIX，不适用于这些约束。不能只把 Bash 命令改成 PowerShell 后宣称支持 Windows。

## 当前结论

当前远程代码不能直接在这个环境完成整套部署。主要障碍是 OpenHarvey 的 Unix 运行管理，以及已选 Langfuse v3 的 Linux 基础设施依赖。当前没有经过验证的“原生 Windows 全套现成部署方案”。

保留 Langfuse 品牌、同时移除 ClickHouse 的**候选研究方向**是 Langfuse v2 的 PostgreSQL 同步存储路径。它不等于已选定的替代方案：官方说明 v2 的安全更新截至 2025 年第一季度，现已结束；Windows 源码构建与当前追踪兼容仍待验证。不能把它描述成受支持的最新版或直接可用。

候选服务组成：

| 服务 | 原生运行方式 | 当前状态 |
|---|---|---|
| OpenHarvey | Python 虚拟环境 + Uvicorn | 需要 Windows 运行管理和工具路径适配 |
| OpenCode 1.16.2 | Windows 可执行程序 | 需验证安装包、启动/退出、Shell 和工具行为 |
| MemoryCore | Node.js 从源码运行 | 需验证依赖安装、SQLite/分词等原生模块与工具执行 |
| MemoryProxy | Node.js 从源码运行 | 需验证 better-sqlite3、node-pty、路径与持久化 |
| MemoryPanel、MemoryKnowledge | 分别运行 Node.js 服务 | 不再使用原来的合并容器启动脚本，分别构建并配置 |
| Langfuse v2 候选 | 从固定源码构建 Web 服务 | 尚未验证 Windows；需旧版采集适配 |
| PostgreSQL | 官方 Windows 安装程序/服务 | Langfuse v2 基础数据库；业务记忆仍使用 SQLite |

候选 Langfuse 必须确认使用 PostgreSQL 同步处理，不开启需要 ClickHouse/Redis/S3 的实验或异步路径。不能执行仓库 `dx`、`infra:dev:*` 或数据库 reset 脚本来绕过问题；其中含 Docker 或清库命令。

## 已核实的源码差异

### OpenHarvey

- `contract_web/runtime_manager.py` 无条件导入 `fcntl`，使用 `flock`、`lsof`、`ps`、Unix 信号及进程启动方式。
- `contract_web/redline.py` 的超时处理使用 `os.killpg`/`SIGKILL`；不能只修复 Web 启动而忽略文档处理子进程。
- `contract_web/feishu_direct.py`、`feishu_quick.py` 也有进程组行为；若启用这些可选功能需独立验收。
- `contract_web/cli.py`、`runtime.py`、记忆插件和发布/召回脚本中有 `python3`、Bash/curl、POSIX 引号和路径假设。

需要实现跨平台进程、文件锁和命令路径层；保留进程身份验证、每账号隔离、锁语义和只读记忆权限。不能用 `shell=True`、放宽命令白名单或吞掉异常替代兼容实现。若允许安装 Git for Windows，其 Bash 可作为工具执行候选，但它不能替代 `fcntl`、Linux 内核或 ClickHouse 服务。

### Agent Memory

需要在目标 Windows 实测 Node 版本、各目录锁文件、原生依赖预编译包/编译工具链。不要把 Linux/macOS 的 node_modules 复制过去。源码运行的 Core、Proxy、Panel、Knowledge 应使用各自的启动入口与工作目录。

替换所有容器路径/域名：`/data/...`、`memory-core:8420`、`host.docker.internal` 改为明确的 Windows 数据目录和本机地址。检查工具生成的 shell 命令、URL/路径转义、SQLite 锁和后台重启恢复。不同 Node 版本需要通过进程级 PATH 隔离，不能假定整个栈使用同一版本。

### Langfuse 候选版本

已读取官方 `v2.95.12` 的源码作为研究样本：根目录要求 Node 20、pnpm 9.5.0，Web 脚本包含 POSIX 环境变量赋值和 `sh -c`，不能直接当作 PowerShell 命令。版本只是核查样本，不表示推荐长期部署。

官方 v2 文档列出 PostgreSQL 基础存储；该源码同时包含新异步架构相关代码。因此仍需在 Windows 验证只用 PostgreSQL 的配置确实能完成写入和查询，不能根据“v2”标签假定所有其他路径都被关闭。

当前 OpenHarvey 导出 OTLP JSON，Core/Proxy 使用 OTel exporter / 新版 Langfuse SDK。v2 的批量入口为 `/api/public/ingestion`，不应将当前 OTLP body 直接发到该入口。需要旧版 ingestion exporter 或本机协议适配器，并验证服务端路由能力；不是换一个 URL 就能解决。

## 若继续研究，先做最小验证，再做全面适配

1. 先明确是否接受已结束官方安全维护的 Langfuse v2；本次没有自动安装或切换到该版本。如果仍要求当前受维护版本，在现有约束下没有已验证方案可交付。
2. 在目标 Windows、独立空目录验证候选 Langfuse：安装依赖、生成 Prisma client、应用全新 PostgreSQL migrations、构建、启动、注册用户/项目、写入一条虚构 trace/span/generation，再通过 UI/API 查回。此步骤必须不用 Docker/WSL/虚拟机或其他机器。
3. 若最小验证失败，记录确切依赖、命令和错误，停止将候选描述为可部署；不通过更换产品或打开远端服务隐瞒失败。
4. 若通过，再实现 OpenHarvey 的 Windows 兼容层，验证启动、文件锁、工具调用、文档成果、进程停止和重启。
5. 验证 Memory 四个进程的安装、初始化、L0 写入、L1 提炼、跨会话召回与持久化。
6. 增加显式可选的 v2 采集路径，保持已有 v3 追踪行为。保留身份范围、来源 ID、父子关系、脱敏、采集大小限制和错误隔离。实际缺失的用量不填零、不估算。
7. 用同一份虚构合同完成 Web → OpenCode → Proxy → Core → Langfuse 的 Windows 实测。只有完成这一阶段，才编写和发布可执行的 PowerShell 部署手册。

这里是开发与验收交接，不是“clone 后直接启动”的承诺。本次没有完成 Windows 兼容修改或 Langfuse v2 exporter。

## 证据入口

- [Langfuse v2 官方部署与维护期限](https://langfuse.com/self-hosting/v2/deployment-guide)
- [Langfuse v2 → v3 架构变化](https://langfuse.com/self-hosting/upgrade/upgrade-guides/upgrade-v2-to-v3)
- [Langfuse v2.95.12 package.json](https://github.com/langfuse/langfuse/blob/v2.95.12/package.json)
- [Langfuse v2.95.12 Web scripts](https://github.com/langfuse/langfuse/blob/v2.95.12/web/package.json)
- [Langfuse v2.95.12 ingestion](https://github.com/langfuse/langfuse/blob/v2.95.12/web/src/pages/api/public/ingestion.ts)
- [OpenHarvey 本地运行管理](../contract_web/runtime_manager.py)
- [当前追踪契约](langfuse-tracing.md)
