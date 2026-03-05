class ManualCorrectionNotFoundError(RuntimeError):
    pass


class ManualCorrectionValidationError(RuntimeError):
    pass


__all__ = [
    "ManualCorrectionNotFoundError",
    "ManualCorrectionValidationError",
]
