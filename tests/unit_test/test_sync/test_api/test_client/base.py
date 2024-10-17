from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel._utils import validate_timeout_delay

from ....base import BaseTestSocket

if TYPE_CHECKING:
    from threading import Lock


class BaseTestClient(BaseTestSocket):
    pass


@contextlib.contextmanager
def dummy_lock_with_timeout(lock: Lock, timeout: float | None, *args: Any, **kwargs: Any) -> Iterator[float | None]:
    with contextlib.ExitStack() as stack:
        if timeout is None:
            stack.enter_context(lock)
        else:
            timeout = validate_timeout_delay(timeout, positive_check=False)
            if lock.acquire(blocking=True, timeout=timeout):
                stack.push(lock)
            else:
                raise TimeoutError()
        yield timeout
