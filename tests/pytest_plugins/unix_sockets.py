from __future__ import annotations

import contextlib
import dataclasses
import os
import pathlib
import secrets
import threading
from collections.abc import Iterator

import pytest


@dataclasses.dataclass(repr=False, eq=False, kw_only=True, frozen=True, slots=True, weakref_slot=True)
class UnixSocketPathFactory:
    _tmp_dir: pathlib.Path
    _cache: set[pathlib.Path] = dataclasses.field(default_factory=set)
    _lock: threading.Lock = dataclasses.field(default_factory=threading.Lock)

    def __call__(self, *, reuse_old_socket: bool = True) -> str:
        with self._lock:
            if reuse_old_socket:
                for unix_socket_path in self._cache:
                    if not unix_socket_path.exists():
                        return os.fspath(unix_socket_path)

            while (unix_socket_path := self._tmp_dir / f"tmp-{secrets.token_hex(3)}.sock").exists():
                continue
            self._cache.add(unix_socket_path)
            return os.fspath(unix_socket_path)


@pytest.fixture(scope="session")
def unix_socket_path_factory(tmp_path_factory: pytest.TempPathFactory) -> Iterator[UnixSocketPathFactory]:
    # NOTE: Do not use tmp_path fixture
    # Unix sockets have a maximum length of 108 characters, therefore pytest's tmp folder could be too big for some test names.

    tmp_dir = tmp_path_factory.getbasetemp().absolute()

    # basetemp starts with /tmp/pytest-of-{username} but when running via tox, basetemp is changed to tox's envtmpdir
    # which, mixed to the socket name, could exceed the 108 characters.
    # Try to reduce the path length by having a relative path.
    with contextlib.suppress(ValueError):
        tmp_dir = tmp_dir.relative_to(os.getcwd())

    unix_socket_path_factory = UnixSocketPathFactory(_tmp_dir=tmp_dir)
    yield unix_socket_path_factory

    with unix_socket_path_factory._lock:
        for unix_socket_path in filter(os.path.exists, unix_socket_path_factory._cache):
            with contextlib.suppress(OSError):
                os.remove(unix_socket_path)
        unix_socket_path_factory._cache.clear()
