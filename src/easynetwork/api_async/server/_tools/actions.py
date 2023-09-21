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
"""Asynchronous network server module"""

from __future__ import annotations

__all__ = []  # type: list[str]

import dataclasses
from collections.abc import AsyncGenerator
from typing import Any, Generic, TypeVar

_T = TypeVar("_T")


@dataclasses.dataclass(slots=True)
class RequestAction(Generic[_T]):
    request: _T

    async def asend(self, generator: AsyncGenerator[None, _T]) -> None:
        await generator.asend(self.request)


@dataclasses.dataclass(slots=True)
class ErrorAction:
    exception: BaseException

    async def asend(self, generator: AsyncGenerator[None, Any]) -> None:
        try:
            await generator.athrow(self.exception)
        finally:
            del self  # Needed to avoid circular reference with raised exception
