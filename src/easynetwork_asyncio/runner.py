# Copyright 2021-2023, Francis Clairicia-Rose-Claire-Josephine
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
"""asyncio engine for easynetwork.api_async
"""

from __future__ import annotations

__all__ = ["AsyncioRunner"]

import asyncio
import contextlib
from collections.abc import Callable, Coroutine
from typing import Any, Self, TypeVar

from easynetwork.api_async.backend.abc import Runner as AbstractRunner

_T = TypeVar("_T")


class AsyncioRunner(AbstractRunner):
    __slots__ = ("__runner",)

    def __init__(self, runner: asyncio.Runner) -> None:
        super().__init__()

        self.__runner: asyncio.Runner = runner

    def __enter__(self) -> Self:
        self.__runner.__enter__()
        return super().__enter__()

    def close(self) -> None:
        return self.__runner.close()

    def run(self, coro_func: Callable[..., Coroutine[Any, Any, _T]], *args: Any) -> _T:
        with contextlib.closing(coro_func(*args)) as coro:  # Avoid ResourceWarning by always closing the coroutine
            return self.__runner.run(coro)
