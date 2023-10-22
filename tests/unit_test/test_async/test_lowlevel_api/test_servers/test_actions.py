from __future__ import annotations

import sys
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from easynetwork.lowlevel.api_async.servers._tools.actions import ActionIterator, ErrorAction, RequestAction

import pytest

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAction:
    @pytest.fixture
    @staticmethod
    def mock_generator(mocker: MockerFixture) -> MagicMock:
        mock_generator = mocker.NonCallableMagicMock(spec=AsyncGenerator)
        mock_generator.asend.return_value = None
        mock_generator.athrow.return_value = None
        mock_generator.aclose.return_value = None
        return mock_generator

    async def test____RequestAction____send_request(self, mock_generator: MagicMock, mocker: MockerFixture) -> None:
        # Arrange
        action = RequestAction(mocker.sentinel.request)

        # Act
        await action.asend(mock_generator)

        # Assert
        assert mock_generator.mock_calls == [mocker.call.asend(mocker.sentinel.request)]
        mock_generator.asend.assert_awaited_once_with(mocker.sentinel.request)

    async def test____ErrorAction____throw_exception(self, mock_generator: MagicMock, mocker: MockerFixture) -> None:
        # Arrange
        exc = ValueError("abc")
        action = ErrorAction(exc)

        # Act
        await action.asend(mock_generator)

        # Assert
        assert mock_generator.mock_calls == [mocker.call.athrow(exc)]
        mock_generator.athrow.assert_awaited_once_with(exc)

    # Test taken from "outcome" project (https://github.com/python-trio/outcome)
    async def test____ErrorAction____does_not_create_reference_cycles(self, mock_generator: MagicMock) -> None:
        # Arrange
        exc = ValueError("abc")
        action = ErrorAction(exc)
        mock_generator.athrow.side_effect = exc

        # Act
        with pytest.raises(ValueError):
            await action.asend(mock_generator)

        # Assert
        # Top frame in the traceback is the current test function; we don't care
        # about its references
        assert exc.__traceback__ is not None
        assert exc.__traceback__.tb_frame is sys._getframe()
        # The next frame down is the 'asend' frame; we want to make sure it
        # doesn't reference the exception (or anything else for that matter, just
        # to be thorough)
        assert exc.__traceback__.tb_next is not None
        unwrap_frame = exc.__traceback__.tb_next.tb_frame
        assert unwrap_frame.f_code.co_name == "asend"
        assert unwrap_frame.f_locals == {}


@pytest.mark.asyncio
class TestActionIterator:
    @pytest.fixture
    @staticmethod
    def request_factory(mocker: MockerFixture) -> AsyncMock:
        return mocker.AsyncMock(spec=lambda: None)

    async def test____dunder_aiter____return_self(self, request_factory: AsyncMock) -> None:
        # Arrange
        action_iterator = ActionIterator(request_factory)

        # Act & Assert
        assert aiter(action_iterator) is action_iterator

    async def test____dunder_anext____yield_actions(self, request_factory: AsyncMock, mocker: MockerFixture) -> None:
        # Arrange
        exc = BaseException()
        request_factory.side_effect = [mocker.sentinel.request, exc, StopAsyncIteration]

        # Act
        actions = [action async for action in ActionIterator(request_factory)]

        # Assert
        assert request_factory.await_count == 3
        assert actions == [RequestAction(mocker.sentinel.request), ErrorAction(exc)]
