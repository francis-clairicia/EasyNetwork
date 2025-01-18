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
"""Server implementation tools module for thread management."""

from __future__ import annotations

__all__ = [
    "NetworkServerThread",
]

import threading as _threading

from ..lowlevel import _utils
from .abc import AbstractNetworkServer


class NetworkServerThread(_threading.Thread):
    """
    A :class:`~threading.Thread` dedicated to network servers.
    """

    def __init__(
        self,
        server: AbstractNetworkServer,
        group: None = None,
        name: str | None = None,
        *,
        daemon: bool | None = None,
    ) -> None:
        """
        Parameters:
            server: the network server implementation to manage.
            group: See :class:`threading.Thread` for details.
            name: See :class:`threading.Thread` for details.
            daemon: See :class:`threading.Thread` for details.
        """

        super().__init__(group=group, target=None, name=name, daemon=daemon)
        self.__server: AbstractNetworkServer = server
        self.__is_up_event: _threading.Event = _threading.Event()

    def start(self) -> None:
        """
        Start the thread's activity and wait until the server is ready for accepting requests.

        It must be called at most once per thread object. It arranges for the object's :meth:`run` method
        to be invoked in a separate thread of control.

        This method will raise a :exc:`RuntimeError` if called more than once on the same thread object.
        """
        super().start()
        self.__is_up_event.wait()

    def run(self) -> None:
        """
        Method representing the thread's activity.

        The only thing done here is to call the server's :meth:`~AbstractNetworkServer.serve_forever` method.
        """
        try:
            self.__server.serve_forever(is_up_event=self.__is_up_event)
        finally:
            self.__is_up_event.set()

    def join(self, timeout: float | None = None) -> None:
        """
        Wait until the thread terminates.

        This calls the server's :meth:`~AbstractNetworkServer.shutdown` method and then the default :meth:`~threading.Thread.join`
        method.

        Parameters:
            timeout: when it present and not None, it should be a floating point number specifying a timeout
                     for the operation in seconds (or fractions thereof).
                     As :meth:`join` always returns None, you must call :meth:`~threading.Thread.is_alive` after join
                     to decide whether a timeout happened -- if the thread is still alive, the join() call timed out.
                     The time taken by :meth:`~AbstractNetworkServer.shutdown` is substracted.
        """
        with _utils.ElapsedTime() as elapsed:
            self.__server.shutdown(timeout=timeout)
        if timeout is not None:
            timeout = elapsed.recompute_timeout(timeout)
        super().join(timeout=timeout)
