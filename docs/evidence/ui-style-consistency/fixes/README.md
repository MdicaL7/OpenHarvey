# 四项 UI 回归修复验收（2026-10-13）

结论：本地修复已通过本轮限定范围的合并就绪验证；**修改尚未提交，远程 UI tip 仍是修复前版本，不应直接合并旧 tip**。未提交、推送、真实合并或部署，目标工作区保持干净。

## 输入与隔离合并

- UI HEAD：`cb1dbdf45b18fb1e6b43a53985e69b80088fe075`，修复工作区 `/Users/dicam/.codex/worktrees/ui-style-consistency/OpenHarvey`。
- 目标：`8c9a3dbb05752ad28792bcd8fb726abcf2c68c29`。
- merge-base：`bc49476681bfb3956995f58745fdc9cb05683b9d`。
- 开始与最终 `git ls-remote` 均确认上述远程 tip，未变化；开始两工作区干净，未覆盖其他人的改动。
- 临时目录 `/tmp/openharvey-ui-fix.1d9V33`。独立 repo 只读引用真实 objects，`merge-tree --write-tree <target> <ui>` 无冲突，提交层复合树 `473e31a0ad799b92f758b1258301944d9d87e569`。
- 在临时 index 上叠加 10 个 static 修复与 2 个测试文件，得到受测代码树 **`d9d5687e726695792164f598109b24aa5da311ff`**。没有创建任何 commit、修改真实 refs/index、或执行真实 merge。受测代码树不包括事后生成的本目录证据文件。
- 目标自分叉没有 static 改动，修复路径与目标变更集合不交叉。复合树的 `contract_web/`、`runtime/`、`scripts/` 与准确目标完全相同；UI 工作区的 12 个代码/测试文件与复合快照逐字节相同。见 [代码 SHA-256 清单](code-manifest.json)。

## 修复内容

1. `static/experience.js:10`：将成功反馈作为 `load(success)` 的参数，只在当前刷新成功且没有失败 job 时显示。读取错误、整理警告和重试入口优先，过期刷新仍被 loadId 拒绝。确认、审核、删除、重试、编辑保存、创建团队使用同一语义，不改 API 权限、版本字段与 operation_id。
2. `static/confirm-dialog.js:5`、`static/settings-ui.js:49、55、107、140`：增加显式取消；设置关闭、Back 触发的视图失效、会话失效、重渲染会取消 pending confirmation。每次对话框独占节点，避免上一轮 queued close 结束新对话框；最终结果验证 isCurrent。Skill、供应商和风险方案的调用方在发送 DELETE 前再验证 generation/当前视图、节点连接状态和目标身份。对应 `admin-ui.js:168–171`、`risk-settings-ui.js:123–125`。
3. `static/workbench.css`、`experience.css`、`settings-ui.css`、`connectors-ui.css`：增加独立的 primary 背景、文字、hover、disabled token，不修改全局 accent 和登录页配色。浅深色 normal/hover/focus/disabled 48 组实测对比度全部 ≥4.5:1，最低约 **4.88:1**。
4. `static/workspace-controls.css:11`：用 `:where()` 降低通用 dialog 表单控件规则优先级，让资料 toolbar 原有紧凑尺寸生效。桌面弹窗 850px，搜索框 530px、两个过滤器各 90px，同排高度 34px；390px 窄屏搜索框单行、两个过滤器下一行，无横向溢出。

新增行为测试：`tests/ui-regressions.test.mjs` 10 项；可选浏览器测试 `tests/ui-browser-regressions.cjs`（不作为依赖安装入口）。把 10 项行为测试放回修复前 UI 代码，得到 2 pass、6 fail、2 timeout/cancelled；修复后 10/10。这些测试执行真实处理函数，不仅检查源码字符串。

## 实跑结果

| 范围 | UI 分支本地修复 | 修复后的复合树 |
| --- | --- | --- |
| 全部前端 `node --test tests/*.test.mjs` | **173/173** | **173/173** |
| 后端完整 `unittest discover` | 361 项：359 pass，2 保护拦截 | 365 项：363 pass，2 保护拦截 |
| 两项受阻测试仅 mock 健康探测补测 | **2/2** | **2/2** |
| 隔离 Chrome 浏览器场景 | **22/22** | **22/22** |
| `git diff --check` | 通过 | 代码与工作区相同 |

两项受阻用例均为已有基线问题：`test_workbench.WorkbenchTests.test_real_docx_export_and_idempotent_persistence` 和 `test_risk_feedback_versions_history_ownership_and_independent_storage`。FakeRuntime 未隔离 TestClient lifespan 中的 RuntimeManager 健康探测，被本轮 guard 阻止；在准确目标的前轮审计中同样如此。本轮未放开真实探测，只补测 `LocalProcessDriver.health = AsyncMock(return_value=False)`。因此**不声称原样后端全套全绿**；未发现修复引入的新后端失败。

22 个浏览器场景包括：

- Skill、风险方案、供应商三条路径分别执行 Back、显式关闭、session-expired、取消、正常确认，共 15 场景。前四类 DELETE=0、正常确认 DELETE=1。残留弹窗均移除，0 pageerror。
- 经验操作成功后仍有 failed job、刷新 error、正常成功，3 场景，分别保留 warn/恢复入口、显示 error、显示 success。
- 浅/深色 × 1440/390px，共 4 场景；每场对经验/设置/连接器 primary 的 normal/hover/focus/disabled 执行 computed-style 对比度检查，并检查资料工具栏尺寸、换行与横向溢出。

截图和 browser-results.json 来自准确修复复合快照，使用假数据/最小宿主页；不能当生产端到端或完整页面矩阵验收。检查过深色桌面资料、浅色窄屏资料、深色窄屏经验、深色桌面设置的截图。原 attribution.json 是旧 `03f34d4` 历史证据，不作为本次修改哈希；本次以本目录 code-manifest.json 为准。

## 可重复命令与边界

使用已有项目 .venv、node_modules 与本机 playwright-core/Chrome，没有安装依赖或付费模型调用。后端测试快照的 node_modules 只读复用已存在依赖。

```sh
node --test tests/*.test.mjs
# 从相应隔离快照运行；A 指此证据目录或复制到 /tmp 的同结构目录。
env -i PATH="$PATH" PYTHONPATH="$A/guard:$PWD" PYTHONDONTWRITEBYTECODE=1 \
  /Users/dicam/CodeDir/OpenHarvey/.venv/bin/python -m unittest discover -s tests -v
env -i PATH="$PATH" PYTHONPATH="$A/guard:$PWD" PYTHONDONTWRITEBYTECODE=1 \
  /Users/dicam/CodeDir/OpenHarvey/.venv/bin/python "$A/restart-tests.py"
PLAYWRIGHT_MODULE_PATH=/path/to/already-installed/playwright-core \
CHROME_PATH=/path/to/chrome node tests/ui-browser-regressions.cjs /tmp/ui-regression-output
```

后端 `env -i` 清除业务配置，guard 阻止非本轮随机测试端口连接、非白名单子进程及生产数据/密钥路径；仅允许本轮临时 fixture 及无网络的 DOCX worker。浏览器使用临时 profile，全部请求由 route mocks 接管；第三方 Orca widget 用空脚本替身。没有启动业务服务、调用外部模型、访问生产数据库或密钥、改变目标工作区。最初浏览器 fixture 缺第三方脚本 stub 时请求被拦截，随后补齐 offline stub；不存在实际外部请求。

未验证：真实登录与会话服务、线上合同记忆提取/召回/团队持久化、部署/CDN、Safari/Firefox、全站每种屏宽。此次权限范围没有执行这些操作。

后续合并前应确认工作区 diff、将本地修复按团队流程提交，再复核届时 tips；若目标变化应重新模拟。当前已验证结果只适用于上述准确目标与本地代码 SHA 清单，不授权自动提交、推送、合并或部署。

归档说明：旧版本反例测试日志的行尾空格已规范化；诊断内容与测试结果未改动。
