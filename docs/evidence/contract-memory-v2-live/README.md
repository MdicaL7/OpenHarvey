# 合同记忆 v2：实验结果与证据入口

**先读[中文实验结果分析](analysis-report.md)。** 它按合同条款、用例和对话步骤解释实际结果，并区分存储、检索和 Agent 采用。

当前结论：已有证据支持本机、小范围、人工确认与审核下的辅助审查试用；不宣称整体生产验收或法律正确性通过。原始评分 **6通过、1失败、2待复核** 原样保留，后续针对三个评分项的复核单独记录。

## 最关键的修正

旧 `preferences-02` 虽然完成全部步骤，但人工把称呼改为“老师”后，实际回答仍将“大哥”当当前约定；仅检查关键词出现的断言漏检。不能继续把该组流程完成表述为“最新偏好采用正确”。组件和 Agent 指令修复后，新团队的新会话正确使用最新正式正文；真实同来源 L3 再提炼没有覆盖人工版本或恢复删除／忽略内容。

- [原始错误回答及当时已修改的正式记录](analysis/records/E10.json)
- [修复后新会话的真实回答](analysis/records/E11.json)
- [删除后的回答与版本历史](analysis/records/E12.json)
- [同来源真实再提炼及保护结果](analysis/records/E13.json)
- [复核评分、模型元数据和逐字证据定位](analysis/review-results.json)

## 证据索引

- [原9用例评分，未覆盖或改写](judge-original-summary.json)
- [21组实际证据摘录及原文件哈希](analysis/manifest.json)
- [机器可读验收边界](acceptance.json)
- [本次复核前的验收快照](acceptance-initial.json)
- [初始执行报告快照](README-initial.md)：历史文件，部分采用层描述已由本报告纠正。
- [部署和恢复说明](../../contract-memory-v2-deployment.md)
- [压缩问题独立记录](runtime-compaction-deferred.md)：按用户要求搁置，不计为本轮记忆质量结论的阻塞项。

工作台：http://127.0.0.1:8081/spaces 。账号 `openharvey-local`；凭据保存在本机 `~/.local/share/openharvey/contract-memory-lab/login.json`，不进入 Git。完整原始证据保存在 `~/.local/share/openharvey/contract-v2-experiment/20261013/`。

OpenHarvey 主目录保持 `codex/contract-memory`；UI 在独立的 `codex/ui-style-consistency` worktree，未合入。当前报告以明确范围的证据判断能力，不用步骤完成数量代替业务结论。
