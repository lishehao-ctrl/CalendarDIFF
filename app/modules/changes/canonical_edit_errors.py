class CanonicalEditNotFoundError(RuntimeError):
    pass


class CanonicalEditValidationError(RuntimeError):
    pass


__all__ = [
    "CanonicalEditNotFoundError",
    "CanonicalEditValidationError",
]
