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
"""Interface to deal with file-descriptor-based sleeping."""

from __future__ import annotations

__all__ = [
    "WakeupSocketPair",
]

import contextlib
import socket

from .socket import set_tcp_nodelay


# Originally come from Trio
# https://github.com/python-trio/trio/blob/v0.29.0/src/trio/_core/_wakeup_socketpair.py
class WakeupSocketPair:
    __slots__ = ("_receive", "_send")

    def __init__(self) -> None:
        self._receive: socket.socket
        self._send: socket.socket

        self._receive, self._send = socket.socketpair()
        self._receive.setblocking(False)
        self._send.setblocking(False)
        # This somewhat reduces the amount of memory wasted queueing up data
        # for wakeups. With these settings, maximum number of 1-byte sends
        # before getting BlockingIOError:
        #   Linux 4.8: 6
        #   macOS (darwin 15.5): 1
        #   Windows 10: 525347
        # Windows you're weird. (And on Windows setting SNDBUF to 0 makes send
        # blocking, even on non-blocking sockets, so don't do that.)
        self._receive.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1)
        self._send.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1)
        # On Windows this is a TCP socket so this might matter. On other
        # platforms this fails b/c AF_UNIX sockets aren't actually TCP.
        with contextlib.suppress(OSError):
            set_tcp_nodelay(self._send, True)

    def close(self) -> None:
        self._send.close()
        self._receive.close()

    def wakeup_thread_and_signal_safe(self) -> None:
        with contextlib.suppress(BlockingIOError, InterruptedError):
            self._send.send(b"\x00")

    def drain(self) -> None:
        try:
            while True:
                self._receive.recv(128)
        except BlockingIOError:
            pass

    def fileno(self) -> int:
        return self._receive.fileno()
