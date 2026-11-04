"""Redis and database-backed memory facades for CloudDesk workflows."""

from .long_term import LongTermMemory, LongTermMemoryNote
from .memory_service import (
    MemoryService,
    ResolutionMemoryRecord,
    recall_customer,
    record_resolution,
)
from .short_term import SHORT_TERM_TTL_SECONDS, ShortTermMemory

__all__ = [
    "SHORT_TERM_TTL_SECONDS",
    "LongTermMemory",
    "LongTermMemoryNote",
    "MemoryService",
    "ResolutionMemoryRecord",
    "ShortTermMemory",
    "recall_customer",
    "record_resolution",
]
