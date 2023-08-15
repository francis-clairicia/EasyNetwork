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

__all__ = [
    "AbstractStandaloneNetworkServer",
]

from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Any, Self

from ...api_async.server.abc import SupportsEventSet

if TYPE_CHECKING:
    from types import TracebackType


class AbstractStandaloneNetworkServer(metaclass=ABCMeta):
    __slots__ = ("__weakref__",)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.server_close()

    def __getstate__(self) -> Any:  # pragma: no cover
        raise TypeError(f"cannot pickle {self.__class__.__name__!r} object")

    @abstractmethod
    def is_serving(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def serve_forever(self, *, is_up_event: SupportsEventSet | None = ...) -> None:
        raise NotImplementedError

    @abstractmethod
    def server_close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def shutdown(self, timeout: float | None = ...) -> None:
        raise NotImplementedError
