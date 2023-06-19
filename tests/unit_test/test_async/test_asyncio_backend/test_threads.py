# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from easynetwork_asyncio.threads import ThreadsPortal

import pytest

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncioThreadsPortal:
    @pytest.fixture
    @staticmethod
    def threads_portal(event_loop: asyncio.AbstractEventLoop) -> ThreadsPortal:
        return ThreadsPortal(loop=event_loop)

    async def test____run_coroutine____use_asyncio_run_coroutine_threadsafe(
        self,
        event_loop: asyncio.AbstractEventLoop,
        threads_portal: ThreadsPortal,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        coro_func_stub: AsyncMock = mocker.async_stub()
        coro_func_stub.return_value = mocker.sentinel.return_value
        mock_run_coroutine_threadsafe: MagicMock = mocker.patch(
            "asyncio.run_coroutine_threadsafe",
            side_effect=asyncio.run_coroutine_threadsafe,
        )

        # Act
        ret_val: Any = None

        def test_thread() -> None:
            nonlocal ret_val

            ret_val = threads_portal.run_coroutine(
                coro_func_stub,
                mocker.sentinel.arg1,
                mocker.sentinel.arg2,
                kw1=mocker.sentinel.kwargs1,
                kw2=mocker.sentinel.kwargs2,
            )

        await asyncio.to_thread(test_thread)

        # Assert
        coro_func_stub.assert_awaited_once_with(
            mocker.sentinel.arg1,
            mocker.sentinel.arg2,
            kw1=mocker.sentinel.kwargs1,
            kw2=mocker.sentinel.kwargs2,
        )
        mock_run_coroutine_threadsafe.assert_called_once_with(mocker.ANY, event_loop)
        assert ret_val is mocker.sentinel.return_value

    async def test____run_coroutine____error_if_called_from_event_loop_thread(
        self,
        threads_portal: ThreadsPortal,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        func_stub: AsyncMock = mocker.async_stub()
        mock_run_coroutine_threadsafe: MagicMock = mocker.patch(
            "asyncio.run_coroutine_threadsafe",
            side_effect=asyncio.run_coroutine_threadsafe,
        )

        # Act
        with pytest.raises(RuntimeError):
            threads_portal.run_coroutine(
                func_stub,
                mocker.sentinel.arg1,
                mocker.sentinel.arg2,
                kw1=mocker.sentinel.kwargs1,
                kw2=mocker.sentinel.kwargs2,
            )

        # Assert
        func_stub.assert_not_called()
        mock_run_coroutine_threadsafe.assert_not_called()

    async def test____run_sync____use_asyncio_event_loop_call_soon_threadsafe(
        self,
        event_loop: asyncio.AbstractEventLoop,
        threads_portal: ThreadsPortal,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        func_stub: MagicMock = mocker.stub()
        func_stub.return_value = mocker.sentinel.return_value
        mock_loop_call_soon_threadsafe: MagicMock = mocker.patch.object(
            event_loop,
            "call_soon_threadsafe",
            side_effect=event_loop.call_soon_threadsafe,
        )

        # Act
        ret_val: Any = None

        def test_thread() -> None:
            nonlocal ret_val

            ret_val = threads_portal.run_sync(
                func_stub,
                mocker.sentinel.arg1,
                mocker.sentinel.arg2,
                kw1=mocker.sentinel.kwargs1,
                kw2=mocker.sentinel.kwargs2,
            )
            mock_loop_call_soon_threadsafe.assert_called_once()

        await asyncio.to_thread(test_thread)

        # Assert
        func_stub.assert_called_once_with(
            mocker.sentinel.arg1,
            mocker.sentinel.arg2,
            kw1=mocker.sentinel.kwargs1,
            kw2=mocker.sentinel.kwargs2,
        )
        assert ret_val is mocker.sentinel.return_value

    async def test____run_sync____error_if_called_from_event_loop_thread(
        self,
        event_loop: asyncio.AbstractEventLoop,
        threads_portal: ThreadsPortal,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        func_stub: MagicMock = mocker.stub()
        mock_loop_call_soon_threadsafe: MagicMock = mocker.patch.object(
            event_loop,
            "call_soon_threadsafe",
            side_effect=event_loop.call_soon_threadsafe,
        )

        # Act
        with pytest.raises(RuntimeError):
            threads_portal.run_sync(
                func_stub,
                mocker.sentinel.arg1,
                mocker.sentinel.arg2,
                kw1=mocker.sentinel.kwargs1,
                kw2=mocker.sentinel.kwargs2,
            )

        # Assert
        func_stub.assert_not_called()
        mock_loop_call_soon_threadsafe.assert_not_called()
