# -*- coding: utf-8 -*-

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Iterator, TypeAlias

from easynetwork.api_sync.client.abc import AbstractNetworkClient

import pytest

ClientType: TypeAlias = AbstractNetworkClient[str, str]


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
    assert isinstance(recv_packet.exception(), ConnectionAbortedError)
