# -*- coding: utf-8 -*-

from __future__ import annotations

import functools
import importlib
import ssl
from typing import Any

import pytest

ALL_MODULES_WHICH_USE_SSL_MODULE: tuple[tuple[str, str], ...] = (
    ("easynetwork.api_async.client.tcp", "_ssl_module"),
    ("easynetwork.api_sync.client.tcp", "_ssl_module"),
    ("easynetwork.tools._utils", "ssl"),
    ("easynetwork_asyncio.backend", "ssl"),
)


@functools.cache
def _verify_ssl_alias(module_name: str, alias_name: str) -> None:
    module = importlib.import_module(module_name)
    retrieved_ssl_module: Any = functools.reduce(getattr, filter(None, alias_name.split(".")), module)
    assert retrieved_ssl_module is ssl, f"Alias name is invalid ({module_name}:{alias_name})"


@pytest.fixture
def simulate_no_ssl_module(monkeypatch: pytest.MonkeyPatch) -> None:
    for module_name, alias_name in ALL_MODULES_WHICH_USE_SSL_MODULE:
        _verify_ssl_alias(module_name, alias_name)
        monkeypatch.setattr(f"{module_name}.{alias_name}", None)
