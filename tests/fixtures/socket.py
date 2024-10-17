from __future__ import annotations

import socket

import pytest

ALL_SOCKET_FAMILIES = frozenset(v for v in dir(socket) if v.startswith("AF_") and v not in {"AF_UNSPEC"})


def socket_family_or_skip(name: str) -> int:
    assert name.startswith("AF_")
    try:
        return getattr(socket, name)
    except AttributeError:
        pytest.skip(f"{name!r} is not defined")


def socket_family_or_None(name: str) -> int | None:
    assert name.startswith("AF_")
    return getattr(socket, name, None)


def AF_UNIX_or_skip() -> int:
    return socket_family_or_skip("AF_UNIX")


def AF_UNIX_or_None() -> int | None:
    return socket_family_or_None("AF_UNIX")
