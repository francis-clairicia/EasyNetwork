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
"""Async generators helper module"""

from __future__ import annotations

__all__ = []  # type: list[str]

import dataclasses
from abc import ABCMeta, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any, Generic, TypeVar

_T_Send = TypeVar("_T_Send")
_T_Yield = TypeVar("_T_Yield")


class AsyncGenAction(Generic[_T_Yield, _T_Send], metaclass=ABCMeta):
    __slots__ = ()

    @abstractmethod
    async def asend(self, generator: AsyncGenerator[_T_Yield, _T_Send]) -> _T_Yield:
        raise NotImplementedError


@dataclasses.dataclass(slots=True)
class SendAction(AsyncGenAction[_T_Yield, _T_Send]):
    value: _T_Send

    async def asend(self, generator: AsyncGenerator[_T_Yield, _T_Send]) -> _T_Yield:
        try:
            return await generator.asend(self.value)
        finally:
            del self


@dataclasses.dataclass(slots=True)
class ThrowAction(AsyncGenAction[_T_Yield, Any]):
    exception: BaseException

    async def asend(self, generator: AsyncGenerator[_T_Yield, Any]) -> _T_Yield:
        try:
            return await generator.athrow(self.exception)
        finally:
            del generator, self  # Needed to avoid circular reference with raised exception
