from __future__ import annotations

import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import TypeAlias

from easynetwork.clients.abc import AbstractNetworkClient
from easynetwork.exceptions import ClientClosedError

import pytest

from ....tools import PlatformMarkers, TimeTest

ClientType: TypeAlias = AbstractNetworkClient[str, str]


pytestmark = [
    pytest.mark.flaky(retries=3, delay=0.1),
    PlatformMarkers.skipif_platform_bsd_because("test failures are all too frequent on CI", skip_only_on_ci=True),
]


@pytest.fixture
def executor(client: ClientType) -> Iterator[ThreadPoolExecutor]:
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            yield executor
        finally:
            client.close()


def test____recv_packet____in_a_background_thread(executor: ThreadPoolExecutor, client: ClientType) -> None:
    recv_packet = executor.submit(client.recv_packet, timeout=30)  # Ensure this thread does not stuck the executor shutdown
    while not recv_packet.running():
        time.sleep(0.1)

    client.send_packet("Hello world!")
    assert recv_packet.result(timeout=30) == "Hello world!"


@pytest.mark.slow
def test____recv_packet____close_while_waiting(executor: ThreadPoolExecutor, client: ClientType) -> None:
    recv_packet = executor.submit(client.recv_packet, timeout=3)
    while not recv_packet.running():
        time.sleep(0.1)

    time.sleep(1.1)

    client.close()
    assert isinstance(recv_packet.exception(timeout=30), (ClientClosedError, ConnectionAbortedError))


@pytest.mark.slow
def test____recv_packet____lock_acquisition____timeout(executor: ThreadPoolExecutor, client: ClientType) -> None:
    background_recv_packet = executor.submit(client.recv_packet, timeout=3)
    while not background_recv_packet.running():
        time.sleep(0.1)

    with TimeTest(1, approx=2e-1), pytest.raises(TimeoutError):
        client.recv_packet(timeout=1)


@pytest.mark.slow
def test____recv_packet____lock_acquisition____timeout_reduced(executor: ThreadPoolExecutor, client: ClientType) -> None:
    background_recv_packet = executor.submit(client.recv_packet, timeout=1)
    while not background_recv_packet.running():
        time.sleep(0.1)

    with TimeTest(3, approx=2e-1), pytest.raises(TimeoutError):
        client.recv_packet(timeout=3)
