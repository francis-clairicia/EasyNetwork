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
"""Task utilities module"""

from __future__ import annotations

__all__ = ["SingleTaskRunner"]

import functools
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any, Generic, ParamSpec, TypeVar

if TYPE_CHECKING:
    from .abc import AsyncBackend, SystemTask


_P = ParamSpec("_P")
_T_co = TypeVar("_T_co", covariant=True)


class SingleTaskRunner(Generic[_T_co]):
    """
    An helper class to execute a coroutine function only once.

    In addition to one-time execution, concurrent calls will simply wait for the result::

        async def expensive_task():
            print("Start expensive task")

            ...

            print("Done")
            return 42

        async def main():
            ...

            task_runner = SingleTaskRunner(backend, expensive_task)
            async with backend.create_task_group() as task_group:
                tasks = [task_group.start_soon(task_runner.run) for _ in range(10)]

            assert all(await t.join() == 42 for t in tasks)
    """

    __slots__ = (
        "__backend",
        "__coro_func",
        "__task",
        "__weakref__",
    )

    def __init__(
        self,
        backend: AsyncBackend,
        coro_func: Callable[_P, Coroutine[Any, Any, _T_co]],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> None:
        """
        Parameters:
            backend: The asynchronous backend interface.
            coro_func: An async function.
            args: Positional arguments to be passed to `coro_func`.
            kwargs: Keyword arguments to be passed to `coro_func`.
        """
        super().__init__()

        self.__backend: AsyncBackend = backend
        self.__coro_func: Callable[[], Coroutine[Any, Any, _T_co]] | None = functools.partial(
            coro_func,
            *args,
            **kwargs,
        )
        self.__task: SystemTask[_T_co] | None = None

    def cancel(self) -> bool:
        """
        Cancel coroutine execution.

        If the runner was not used yet, :meth:`run` will not call `coro_func` and raise ``backend.get_cancelled_exc_class()``.

        If `coro_func` is already running, a cancellation request is sent to the coroutine.

        Returns:
            :data:`True` in case of success, :data:`False` otherwise.
        """
        self.__coro_func = None
        if self.__task is not None:
            return self.__task.cancel()
        return True

    async def run(self) -> _T_co:
        """
        Executes the coroutine `coro_func`.

        Raises:
            Exception: Whatever ``coro_func`` raises.

        Returns:
            Whatever ``coro_func`` returns.
        """
        must_cancel_inner_task: bool = False
        if self.__task is None:
            must_cancel_inner_task = True
            if self.__coro_func is None:
                self.__task = self.__backend.spawn_task(self.__backend.sleep_forever)
                self.__task.cancel()
            else:
                coro_func = self.__coro_func
                self.__coro_func = None
                self.__task = self.__backend.spawn_task(coro_func)
                del coro_func

        try:
            if must_cancel_inner_task:
                return await self.__task.join_or_cancel()
            else:
                return await self.__task.join()
        finally:
            del self  # Avoid circular reference with raised exception (if any)
