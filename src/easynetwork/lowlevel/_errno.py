from __future__ import annotations

__all__ = ["error_from_errno"]

import os


def error_from_errno(errno: int, msg: str = "{strerror}") -> OSError:
    msg = msg.format(strerror=os.strerror(errno))
    return OSError(errno, msg)
