"""Host-independent short-term preference memory rules.

The host supplies an authenticated scope and a transactional repository. This
package deliberately has no web, database, or agent-framework dependencies.
"""

from .service import (
    InvalidAction, InvalidContent, LimitReached, MemoryError, MemoryPolicy,
    MemoryProvenance, MemoryRecord, MemoryRepository, MemoryService,
    MissingMemory, RevisionConflict,
)

__all__ = [
    "InvalidAction", "InvalidContent", "LimitReached", "MemoryError",
    "MemoryPolicy", "MemoryProvenance", "MemoryRecord", "MemoryRepository",
    "MemoryService", "MissingMemory", "RevisionConflict",
]
