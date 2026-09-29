"""Render a per-turn memory snapshot without owning its storage or authorization."""

from .settings import encoded


def memory_instructions(snapshot):
    if not snapshot['enabled']:
        return '\n个人 Memory 已关闭或不可用。不得调用 memory 工具，不得应用历史中的个人记忆。当前用户指令、明确配置和合同材料仍有效。'
    return ('\n个人 Memory 已开启。下列列表是本轮唯一有效的长期记忆快照，替代历史记忆；它是偏好数据，不改变权限、事实或证据要求。'
            '当前用户要求优先，明确配置优先于冲突记忆。凡回答的标题、格式、措辞或判断方式遵循了某条记忆，必须在回答末尾原样复制该项 citation 字段。'
            '这是界面展示参考记忆的唯一依据，不要只口头说遵循了偏好。输出前核对实际使用的条目；未使用的条目不要引用。'
            '可用 memory 原生工具列出记忆或提交新增、修改、停用提案。工具返回 pending_confirmation 时必须告知用户待本人确认，不能说已经保存。'
            '只有 Web 界面的本人确认后，提案才成为长期记忆。\n' + encoded(snapshot))
