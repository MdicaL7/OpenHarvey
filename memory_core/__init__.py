"""Host-independent short-term preference memory rules.

The host supplies an authenticated scope and a transactional repository. This
package deliberately has no web, database, or agent-framework dependencies.
"""

from .service import (
    InvalidAction, InvalidContent, LimitReached, MemoryError, MemoryPolicy,
    MemoryProvenance, MemoryRecord, MemoryRepository, MemoryService,
    MissingMemory, RevisionConflict,
)
from .knowledge import Change, KnowledgeConflict, KnowledgeError, next_revision

__all__ = [
    "InvalidAction", "InvalidContent", "LimitReached", "MemoryError",
    "MemoryPolicy", "MemoryProvenance", "MemoryRecord", "MemoryRepository",
    "MemoryService", "MissingMemory", "RevisionConflict",
    "Change", "KnowledgeConflict", "KnowledgeError", "next_revision",
]
