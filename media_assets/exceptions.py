class MediaValidationError(Exception):
    """Raised by anything in validation.py/scanning.py when a file fails a
    check. `reason` is short and safe to store in MediaAsset.failure_reason
    (and to show an owner), never raw exception internals/stack traces."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)
