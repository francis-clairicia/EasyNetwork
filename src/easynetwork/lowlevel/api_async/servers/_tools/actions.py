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
"""Low-level asynchronous server module"""

from __future__ import annotations

__all__ = []  # type: list[str]

import dataclasses
from abc import ABCMeta, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from typing import Any, Generic, TypeVar

_T = TypeVar("_T")


class Action(Generic[_T], metaclass=ABCMeta):
    __slots__ = ()

    @abstractmethod
    async def asend(self, generator: AsyncGenerator[None, _T]) -> None:
        raise NotImplementedError


@dataclasses.dataclass(slots=True)
class RequestAction(Action[_T]):
    request: _T

    async def asend(self, generator: AsyncGenerator[None, _T]) -> None:
        try:
            await generator.asend(self.request)
        finally:
            del self


@dataclasses.dataclass(slots=True)
class ErrorAction(Action[Any]):
    exception: BaseException

    async def asend(self, generator: AsyncGenerator[None, Any]) -> None:
        try:
            await generator.athrow(self.exception)
        finally:
            del self  # Needed to avoid circular reference with raised exception


@dataclasses.dataclass(slots=True)
class ActionIterator(Generic[_T]):
    request_factory: Callable[[], Awaitable[_T]]

    def __aiter__(self) -> AsyncIterator[Action[_T]]:
        return self

    async def __anext__(self) -> Action[_T]:
        try:
            request = await self.request_factory()
        except StopAsyncIteration:
            raise
        except BaseException as exc:
            return ErrorAction(exc)
        return RequestAction(request)
