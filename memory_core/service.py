"""Memory domain operations; transaction and identity belong to the caller."""

from dataclasses import dataclass
from typing import Callable, Protocol
import secrets
import time


class MemoryError(Exception):
    """Base class for predictable domain failures."""


class InvalidAction(MemoryError):
    pass


class MissingMemory(MemoryError):
    pass


class RevisionConflict(MemoryError):
    pass


class InvalidContent(MemoryError):
    pass


class LimitReached(MemoryError):
    pass


@dataclass(frozen=True)
class MemoryPolicy:
    item_limit: int = 500
    total_limit: int = 12000


@dataclass(frozen=True)
class MemoryProvenance:
    source: str = "manual"
    thread_id: str | None = None
    message_id: str | None = None


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    content: str
    revision: int
    created: float
    updated: float
    source: str
    source_thread_id: str | None
    source_message_id: str | None


class MemoryRepository(Protocol):
    """Operate within the caller's transaction; never start or commit one."""

    def list(self, scope_id: str) -> list[MemoryRecord]: ...
    def get(self, scope_id: str, memory_id: str) -> MemoryRecord | None: ...
    def used_chars(self, scope_id: str) -> int: ...
    def insert(self, scope_id: str, record: MemoryRecord) -> None: ...
    def replace(self, scope_id: str, record: MemoryRecord) -> None: ...
    def delete(self, scope_id: str, memory_id: str) -> None: ...


class MemoryService:
    def __init__(self, repository: MemoryRepository, policy: MemoryPolicy = MemoryPolicy(),
                 *, new_id: Callable[[], str] | None = None,
                 now: Callable[[], float] = time.time):
        self.repository = repository
        self.policy = policy
        self.new_id = new_id or (lambda: secrets.token_hex(12))
        self.now = now

    def list(self, scope_id: str) -> list[MemoryRecord]:
        return self.repository.list(scope_id)

    def snapshot(self, scope_id: str, enabled: bool) -> tuple[MemoryRecord, ...]:
        return tuple(self.list(scope_id)) if enabled else ()

    def create(self, scope_id: str, content: str, provenance: MemoryProvenance = MemoryProvenance()) -> MemoryRecord:
        content = self._content(content)
        self._check_capacity(scope_id, content)
        now = self.now()
        record = MemoryRecord(self.new_id(), content, 1, now, now,
                              provenance.source, provenance.thread_id, provenance.message_id)
        self.repository.insert(scope_id, record)
        return record

    def update(self, scope_id: str, memory_id: str, expected_revision: int,
               content: str, provenance: MemoryProvenance = MemoryProvenance()) -> MemoryRecord:
        prior = self._prior(scope_id, memory_id, expected_revision)
        content = self._content(content)
        self._check_capacity(scope_id, content, prior)
        record = MemoryRecord(prior.id, content, prior.revision + 1, prior.created,
                              self.now(), provenance.source, provenance.thread_id, provenance.message_id)
        self.repository.replace(scope_id, record)
        return record

    def delete(self, scope_id: str, memory_id: str, expected_revision: int) -> MemoryRecord:
        prior = self._prior(scope_id, memory_id, expected_revision)
        self.repository.delete(scope_id, memory_id)
        return prior

    def _prior(self, scope_id: str, memory_id: str, revision: int) -> MemoryRecord:
        prior = self.repository.get(scope_id, memory_id)
        if prior is None:
            raise MissingMemory()
        if type(revision) is not int or revision != prior.revision:
            raise RevisionConflict()
        return prior

    def _content(self, content: str) -> str:
        if (not isinstance(content, str) or not content.strip()
                or len(content.strip()) > self.policy.item_limit
                or any(ord(c) < 32 and c not in "\n\t" for c in content)):
            raise InvalidContent()
        return content.strip()

    def _check_capacity(self, scope_id: str, content: str, prior: MemoryRecord | None = None) -> None:
        if self.repository.used_chars(scope_id) - (len(prior.content) if prior else 0) + len(content) > self.policy.total_limit:
            raise LimitReached()
