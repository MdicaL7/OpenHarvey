"""Portable validation for versioned knowledge and human-reviewed proposals."""

from dataclasses import dataclass


KINDS = frozenset({'preference', 'rule', 'template', 'case'})
ACTIONS = frozenset({'create', 'update', 'disable'})
PROPOSAL_STATES = frozenset({'pending', 'applied', 'ignored'})
ITEM_STATES = frozenset({'active', 'inactive'})


class KnowledgeError(ValueError):
    pass


class KnowledgeConflict(KnowledgeError):
    pass


@dataclass(frozen=True)
class Change:
    kind: str
    action: str
    content: dict
    target_id: str | None = None
    base_revision: int | None = None

    def validate(self):
        if self.kind not in KINDS or self.action not in ACTIONS:
            raise KnowledgeError('知识类别或操作无效')
        if not isinstance(self.content, dict):
            raise KnowledgeError('知识内容必须是对象')
        if self.action == 'create':
            if self.target_id is not None or self.base_revision is not None:
                raise KnowledgeError('新增知识不能指定现有版本')
        elif not self.target_id or type(self.base_revision) is not int or self.base_revision < 1:
            raise KnowledgeError('修改或停用需要目标及原版本')
        if self.action != 'disable' and not str(self.content.get('content', '')).strip():
            raise KnowledgeError('知识内容不能为空')
        return self


def next_revision(change: Change, current_revision: int | None) -> int:
    change.validate()
    if change.action == 'create':
        if current_revision is not None:
            raise KnowledgeConflict('知识已经存在')
        return 1
    if current_revision != change.base_revision:
        raise KnowledgeConflict('知识版本已变化，请重新核对')
    return current_revision + 1
