# Copyright 2021-2024, Francis Clairicia-Rose-Claire-Josephine
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

__all__ = []  # type: list[str]

import dataclasses
import sys
from abc import ABCMeta, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any, Generic, Protocol, TypeVar

from . import _utils

_T_Send = TypeVar("_T_Send")
_T_Yield = TypeVar("_T_Yield")


class AsyncGenAction(Generic[_T_Send], metaclass=ABCMeta):
    __slots__ = ()

    @abstractmethod
    async def asend(self, generator: AsyncGenerator[_T_Yield, _T_Send]) -> _T_Yield:
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


class _GetAsyncGenHooks(Protocol):
    @staticmethod
    @abstractmethod
    def __call__() -> sys._asyncgen_hooks: ...


class _SetAsyncGenHooks(Protocol):
    @staticmethod
    @abstractmethod
    def __call__(firstiter: sys._AsyncgenHook = ..., finalizer: sys._AsyncgenHook = ...) -> None: ...


async def anext_without_asyncgen_hook(
    agen: AsyncGenerator[_T_Yield, Any],
    /,
    *,
    _get_asyncgen_hooks: _GetAsyncGenHooks = sys.get_asyncgen_hooks,
    _set_asyncgen_hooks: _SetAsyncGenHooks = sys.set_asyncgen_hooks,
) -> _T_Yield:
    previous_firstiter_hook = _get_asyncgen_hooks().firstiter
    _set_asyncgen_hooks(firstiter=None)
    try:
        anext_coroutine = anext(agen)
    finally:
        _set_asyncgen_hooks(firstiter=previous_firstiter_hook)
        previous_firstiter_hook = None
    try:
        return await anext_coroutine
    except BaseException as exc:
        _utils.remove_traceback_frames_in_place(exc, 1)
        raise
