class StrictMemoryEngineError(RuntimeError):
    """Base error for the strict pipeline."""


class StrictConfigurationError(StrictMemoryEngineError):
    """The strict pipeline configuration violates its formal contract."""


class StrictStageUnavailableError(StrictMemoryEngineError):
    """A requested strict stage has no registered implementation."""


class IdempotencyConflictError(StrictMemoryEngineError):
    """A source event id was replayed with different semantic content."""
