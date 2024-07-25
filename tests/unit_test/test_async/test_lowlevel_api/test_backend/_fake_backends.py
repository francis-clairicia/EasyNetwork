from __future__ import annotations

from typing import Any, NoReturn, final, no_type_check

from easynetwork.lowlevel.api_async.backend.abc import AsyncBackend


class BaseFakeBackend(AsyncBackend):
    @no_type_check
    def bootstrap(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def sleep(self, delay: float) -> None:
        raise NotImplementedError

    async def sleep_forever(self) -> NoReturn:
        raise NotImplementedError

    def current_time(self) -> float:
        raise NotImplementedError

    async def coro_yield(self) -> None:
        raise NotImplementedError

    async def cancel_shielded_coro_yield(self) -> None:
        raise NotImplementedError

    async def ignore_cancellation(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def timeout(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def timeout_at(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def move_on_after(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def move_on_at(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def open_cancel_scope(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def get_cancelled_exc_class(self) -> type[BaseException]:
        raise NotImplementedError

    def create_task_group(self) -> Any:
        raise NotImplementedError

    def get_current_task(self) -> Any:
        raise NotImplementedError

    async def create_tcp_connection(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def wrap_stream_socket(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def create_tcp_listeners(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def create_udp_endpoint(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def wrap_connected_datagram_socket(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def create_udp_listeners(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def create_lock(self) -> Any:
        raise NotImplementedError

    def create_event(self) -> Any:
        raise NotImplementedError

    def create_condition_var(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    @no_type_check
    async def run_in_thread(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def create_threads_portal(self) -> Any:
        raise NotImplementedError


@final
class FakeAsyncIOBackend(BaseFakeBackend):
    pass


@final
class FakeTrioBackend(BaseFakeBackend):
    pass


@final
class FakeCurioBackend(BaseFakeBackend):
    pass
