from ..schemas.public import Problem


class PublicError(Exception):
    def __init__(
        self, status: int, code: str, message: str, *, advice="never", details=None
    ):
        self.status = status
        self.problem = Problem(
            code=code, message=message, retry_advice=advice, details=details or {}
        )
        super().__init__(message)
