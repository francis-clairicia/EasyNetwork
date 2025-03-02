# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
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
"""Async generators helper module."""

from __future__ import annotations

__all__ = [
    "AsyncGenAction",
    "SendAction",
    "ThrowAction",
]

import dataclasses
from abc import ABCMeta, abstractmethod
from collections.abc import AsyncGenerator, Coroutine
from typing import Any, Generic, TypeVar

_T_Send = TypeVar("_T_Send")
_T_Yield = TypeVar("_T_Yield")


class AsyncGenAction(Generic[_T_Send], metaclass=ABCMeta):
    __slots__ = ()

    @abstractmethod
    def asend(self, generator: AsyncGenerator[_T_Yield, _T_Send]) -> Coroutine[Any, Any, _T_Yield]:
        raise NotImplementedError


@dataclasses.dataclass(slots=True)
class SendAction(AsyncGenAction[_T_Send]):
    value: _T_Send

    async def asend(self, generator: AsyncGenerator[_T_Yield, _T_Send]) -> _T_Yield:
        return await generator.asend(self.value)


@dataclasses.dataclass(slots=True)
class ThrowAction(AsyncGenAction[Any]):
    exception: BaseException

    async def asend(self, generator: AsyncGenerator[_T_Yield, Any]) -> _T_Yield:
        try:
            match self.exception:
                case GeneratorExit():
                    await generator.aclose()
                    raise self.exception
                case _:
                    return await generator.athrow(self.exception)
        finally:
            del generator, self  # Needed to avoid circular reference with raised exception
