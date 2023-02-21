# -*- coding: Utf-8 -*-
# Copyright (c) 2021-2023, Francis Clairicia-Rose-Claire-Josephine
#
#
"""Network server request executors module"""

from __future__ import annotations

__all__ = ["ForkingRequestExecutor"]

import concurrent.futures
import os
from typing import Callable, ParamSpec

from .abc import AbstractRequestExecutor, RequestFuture

_P = ParamSpec("_P")


class ForkingRequestExecutor(AbstractRequestExecutor):
    __slots__ = ("__fork", "__max_children", "__block_on_close", "__active_children")

    def __init__(self, *, max_children: int = 40, block_on_close: bool = True) -> None:
        super().__init__()

        try:
            fork: Callable[[], int] = getattr(os, "fork")
        except AttributeError:
            raise NotImplementedError("fork() not supported on this platform") from None

        max_children = int(max_children)
        if max_children <= 0:
            raise ValueError("max_children must not be <= 0")
        self.__fork: Callable[[], int] = fork
        self.__max_children: int = max_children
        self.__block_on_close: bool = bool(block_on_close)
        self.__active_children: dict[int, concurrent.futures.Future[None]] = {}

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
                self.__discard_children(pid)
            except ChildProcessError:
                # we don't have any children, we're done
                self.__discard_all_children()
            except OSError:
                break

        # Now reap all defunct children.
        for pid in self.__active_children.copy():
            try:
                flags = 0 if blocking else getattr(os, "WNOHANG")
                pid, _ = os.waitpid(pid, flags)
                # if the child hasn't exited yet, pid will be 0 and ignored by
                # discard() below
                self.__discard_children(pid)
            except ChildProcessError:
                # someone else reaped it
                self.__discard_children(pid)
            except OSError:
                pass

    def __discard_children(self, pid: int) -> None:
        future = self.__active_children.pop(pid, None)
        if future is not None and not future.done():
            future.set_result(None)

    def __discard_all_children(self) -> None:
        children, self.__active_children = self.__active_children, {}
        for future in list(children.values()):
            if not future.done():
                future.set_result(None)

    def execute(self, __request_handler: Callable[_P, None], /, *args: _P.args, **kwargs: _P.kwargs) -> RequestFuture:
        """Fork a new subprocess to process the request."""
        fork: Callable[[], int] = self.__fork
        pid = fork()
        if pid:
            # Parent process
            try:
                fut = self.__active_children[pid]
            except KeyError:
                pass
            else:
                fut.cancel()
            self.__active_children[pid] = fut = concurrent.futures.Future()
            return RequestFuture(fut)

        # Child process.
        # This must never return, hence os._exit()!
        status = 1
        try:
            __request_handler(*args, **kwargs)
            status = 0
        finally:
            os._exit(status)

    def service_actions(self) -> None:
        """Collect the zombie child processes regularly in the ForkingRequestExecutor.
        service_actions is called in the AbstractNetworkServer's serve_forever loop.
        """
        super().service_actions()
        self.collect_children()

    def shutdown(self) -> None:
        try:
            self.collect_children(blocking=self.__block_on_close)
        finally:
            super().shutdown()

    def get_active_children(self) -> frozenset[int]:
        return frozenset(self.__active_children)
