# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network server request executors module"""

from __future__ import annotations

__all__ = ["ForkingRequestExecutor"]

import os
from typing import TYPE_CHECKING, Any, Callable, TypeVar

from .abc import AbstractRequestExecutor

if TYPE_CHECKING:
    from _typeshed import ExcInfo

_RequestVar = TypeVar("_RequestVar")
_ClientVar = TypeVar("_ClientVar")


class ForkingRequestExecutor(AbstractRequestExecutor):
    __slots__ = ("__fork", "__max_children", "__block_on_close", "__active_children")

    def __init__(self, *, max_children: int = 40, block_on_close: bool = True) -> None:
        try:
            fork: Callable[[], int] = getattr(os, "fork")
        except AttributeError:
            raise NotImplementedError("fork() not supported on this platform")

        super().__init__()

        max_children = int(max_children)
        if max_children <= 0:
            raise ValueError("max_children must not be <= 0")
        self.__fork: Callable[[], int] = fork
        self.__max_children: int = max_children
        self.__block_on_close: bool = bool(block_on_close)
        self.__active_children: set[int] = set()

    def collect_children(self, *, blocking: bool = False) -> None:
        """Internal routine to wait for children that have exited."""

        # If we're above the max number of children, wait and reap them until
        # we go back below threshold. Note that we use waitpid(-1) below to be
        # able to collect children in size(<defunct children>) syscalls instead
        # of size(<children>): the downside is that this might reap children
        # which we didn't spawn, which is why we only resort to this when we're
        # above max_children.
        while len(self.__active_children) >= self.__max_children:
            try:
                pid, _ = os.waitpid(-1, 0)
                self.__active_children.discard(pid)
            except ChildProcessError:
                # we don't have any children, we're done
                self.__active_children.clear()
            except OSError:
                break

        # Now reap all defunct children.
        for pid in self.__active_children.copy():
            try:
                flags = 0 if blocking else getattr(os, "WNOHANG")
                pid, _ = os.waitpid(pid, flags)
                # if the child hasn't exited yet, pid will be 0 and ignored by
                # discard() below
                self.__active_children.discard(pid)
            except ChildProcessError:
                # someone else reaped it
                self.__active_children.discard(pid)
            except OSError:
                pass

    def execute(
        self,
        request_handler: Callable[[_RequestVar, _ClientVar], None],
        request_teardown: tuple[Callable[[_ClientVar, dict[str, Any]], None], dict[str, Any] | None] | None,
        request: _RequestVar,
        client: _ClientVar,
        error_handler: Callable[[_ClientVar, ExcInfo], None],
    ) -> None:
        """Fork a new subprocess to process the request."""
        fork: Callable[[], int] = self.__fork
        pid = fork()
        if pid:
            # Parent process
            self.__active_children.add(pid)
            return

        # Child process.
        # This must never return, hence os._exit()!
        status = 1
        try:
            request_handler(request, client)
            status = 0
        except Exception:
            error_handler(client, self.get_exc_info())
        finally:
            try:
                if request_teardown is not None:
                    request_teardown_func, request_context = request_teardown
                    request_teardown_func(client, request_context or {})
            except Exception:
                error_handler(client, self.get_exc_info())
            finally:
                os._exit(status)

    def service_actions(self) -> None:
        """Collect the zombie child processes regularly in the ForkingRequestExecutor.
        service_actions is called in the AbstractNetworkServer's serve_forever loop.
        """
        super().service_actions()
        self.collect_children()

    def on_server_close(self) -> None:
        super().on_server_close()
        self.collect_children(blocking=self.__block_on_close)
