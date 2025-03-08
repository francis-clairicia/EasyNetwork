# Copyright 2021-2025, Francis Clairicia-Rose-Claire-Josephine
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
"""asyncio engine for easynetwork.api_async"""

from __future__ import annotations

__all__ = [
    "wait_until_readable",
    "wait_until_writable",
]

import asyncio
import socket as _socket


def wait_until_readable(sock: _socket.socket, loop: asyncio.AbstractEventLoop) -> asyncio.Future[None]:
    def on_fut_done(f: asyncio.Future[None]) -> None:
        loop.remove_reader(sock)

    def wakeup(f: asyncio.Future[None]) -> None:
        if not f.done():
            f.set_result(None)

    f = loop.create_future()
    loop.add_reader(sock, wakeup, f)
    f.add_done_callback(on_fut_done)
    return f


def wait_until_writable(sock: _socket.socket, loop: asyncio.AbstractEventLoop) -> asyncio.Future[None]:
    def on_fut_done(f: asyncio.Future[None]) -> None:
        loop.remove_writer(sock)

    def wakeup(f: asyncio.Future[None]) -> None:
        if not f.done():
            f.set_result(None)

    f = loop.create_future()
    loop.add_writer(sock, wakeup, f)
    f.add_done_callback(on_fut_done)
    return f
