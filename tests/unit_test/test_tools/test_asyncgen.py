from __future__ import annotations

import sys
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel._asyncgen import SendAction, ThrowAction

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class TestAsyncGenAction:
    @pytest.fixture
    @staticmethod
    def mock_generator(mocker: MockerFixture) -> MagicMock:
        mock_generator = mocker.NonCallableMagicMock(spec=AsyncGenerator)
        mock_generator.asend.return_value = None
        mock_generator.athrow.return_value = None
        mock_generator.aclose.return_value = None
        return mock_generator

    async def test____SendAction____send_value(self, mock_generator: MagicMock, mocker: MockerFixture) -> None:
        # Arrange
        mock_generator.asend.return_value = mocker.sentinel.to_yield_from_send
        action: SendAction[Any, Any] = SendAction(mocker.sentinel.value)

        # Act
        to_yield = await action.asend(mock_generator)

        # Assert
        assert mock_generator.mock_calls == [mocker.call.asend(mocker.sentinel.value)]
        mock_generator.asend.assert_awaited_once_with(mocker.sentinel.value)
        assert to_yield is mocker.sentinel.to_yield_from_send

    async def test____ThrowAction____throw_exception(self, mock_generator: MagicMock, mocker: MockerFixture) -> None:
        # Arrange
        exc = ValueError("abc")
        mock_generator.athrow.return_value = mocker.sentinel.to_yield_from_throw
        action: ThrowAction[Any] = ThrowAction(exc)

        # Act
        to_yield = await action.asend(mock_generator)

        # Assert
        assert mock_generator.mock_calls == [mocker.call.athrow(exc)]
        mock_generator.athrow.assert_awaited_once_with(exc)
        assert to_yield is mocker.sentinel.to_yield_from_throw

    async def test____ThrowAction____close_generator(self, mock_generator: MagicMock, mocker: MockerFixture) -> None:
        # Arrange
        exc = GeneratorExit()
        action: ThrowAction[Any] = ThrowAction(exc)

        # Act
        with pytest.raises(GeneratorExit) as exc_info:
            await action.asend(mock_generator)

        # Assert
        assert exc_info.value is exc
        assert mock_generator.mock_calls == [mocker.call.aclose()]
        mock_generator.aclose.assert_awaited_once_with()

    # Test taken from "outcome" project (https://github.com/python-trio/outcome)
    async def test____ThrowAction____does_not_create_reference_cycles(self, mock_generator: MagicMock) -> None:
        # Arrange
        exc = ValueError("abc")
        action: ThrowAction[Any] = ThrowAction(exc)
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
