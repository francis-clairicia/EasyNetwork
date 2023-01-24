# -*- coding: Utf-8 -*-

from __future__ import annotations

from threading import Thread
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from easynetwork.server.abc import AbstractNetworkServer


def run_server_in_thread(server: AbstractNetworkServer[Any, Any]) -> None:
    t = Thread(target=server.serve_forever, daemon=True)
    assert t.daemon
    t.start()
