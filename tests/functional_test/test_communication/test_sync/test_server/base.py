from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import NamedTuple

from easynetwork.exceptions import ServerAlreadyRunning, ServerClosedError
from easynetwork.servers.abc import AbstractNetworkServer

import pytest


class _ServerBootstrapInfo(NamedTuple):
    thread: threading.Thread
    is_up_event: threading.Event


class BaseTestThreadedServer:

    @pytest.fixture(autouse=True)
    @staticmethod
    def logger_crash_enable(logger_crash_enable: Event, caplog: pytest.LogCaptureFixture) -> Event:
        logger_crash_enable.set()
        caplog.set_level(logging.WARNING, "easynetwork")
        return logger_crash_enable

    @pytest.fixture
    @staticmethod
    def server_bootstrap_delay(request: pytest.FixtureRequest) -> float:
        return float(getattr(request, "param", 0))

    @pytest.fixture  # DO NOT SET autouse=True
    @staticmethod
    def _bootstrap_server(server: AbstractNetworkServer, server_bootstrap_delay: float) -> Generator[_ServerBootstrapInfo]:

        event = threading.Event()

        def serve_forever(server: AbstractNetworkServer, event: threading.Event) -> None:
            try:
                with contextlib.suppress(ServerClosedError):
                    server.serve_forever(is_up_event=event)
            except BaseException:
                logger: logging.Logger = getattr(server, "logger", None) or logging.getLogger("easynetwork")
                logger.exception("serve_forever() crash")

        thread = threading.Thread(target=serve_forever, args=(server, event), daemon=True)

        if server_bootstrap_delay > 0:
            # In order to make actions possible before serve_forever() call, delay the thread start by 100ms
            threading.Timer(server_bootstrap_delay, thread.start).start()
        else:
            assert server_bootstrap_delay == 0
            thread.start()

        yield _ServerBootstrapInfo(thread, event)
        server.shutdown(timeout=2.0)

    @pytest.fixture  # DO NOT SET autouse=True
    @staticmethod
    def run_server(_bootstrap_server: _ServerBootstrapInfo) -> threading.Event:
        return _bootstrap_server.is_up_event

    @pytest.fixture  # DO NOT SET autouse=True
    @staticmethod
    def server_thread(_bootstrap_server: _ServerBootstrapInfo) -> threading.Thread:
        return _bootstrap_server.thread

    def test____server_close____idempotent(self, server: AbstractNetworkServer) -> None:
        server.server_close()
        server.server_close()
        server.server_close()

    def test____server_close____while_server_is_running(
        self,
        server: AbstractNetworkServer,
        run_server: threading.Event,
        server_thread: threading.Thread,
    ) -> None:
        if not run_server.wait(timeout=1.0):
            raise TimeoutError("run_server")
        server.server_close()
        server_thread.join(timeout=1)

        # There is no client so the server loop should stop by itself
        assert not server_thread.is_alive()
        assert not server.is_serving()
        assert not server.is_listening()

    def test____serve_forever____error_already_running(
        self,
        run_server: threading.Event,
        server: AbstractNetworkServer,
    ) -> None:
        if not run_server.wait(timeout=1.0):
            raise TimeoutError("run_server")
        with pytest.raises(ServerAlreadyRunning):
            server.serve_forever()

    def test____serve_forever____error_closed_server(
        self,
        server: AbstractNetworkServer,
    ) -> None:
        server.server_close()
        with pytest.raises(ServerClosedError):
            server.serve_forever()

    def test____serve_forever____without_is_up_event(
        self,
        server: AbstractNetworkServer,
    ) -> None:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        time.sleep(1.0)
        if not server.is_serving():
            pytest.fail("Timeout error")

        server.shutdown()

    @pytest.mark.parametrize("server_is_up", [False, True], ids=lambda p: f"server_is_up__{p}")
    @pytest.mark.parametrize("server_bootstrap_delay", [pytest.param(0.1, id=pytest.HIDDEN_PARAM)], indirect=True)
    def test____serve_forever____concurrent_shutdown(
        self,
        server_is_up: bool,
        server: AbstractNetworkServer,
        run_server: threading.Event,
    ) -> None:
        if server_is_up:
            if not run_server.wait(timeout=1.0):
                raise TimeoutError("run_server")

        with ThreadPoolExecutor() as executor:
            for _ in range(10):
                executor.submit(server.shutdown)
