from __future__ import annotations

import contextlib
import sys
from collections.abc import AsyncGenerator, AsyncIterator
from typing import TYPE_CHECKING, Any

from easynetwork.lowlevel._asyncgen import SendAction, ThrowAction, anext_without_asyncgen_hook

import pytest
import pytest_asyncio

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
        action: SendAction[Any] = SendAction(mocker.sentinel.value)

        # Act
        to_yield: Any = await action.asend(mock_generator)

        # Assert
        assert mock_generator.mock_calls == [mocker.call.asend(mocker.sentinel.value)]
        mock_generator.asend.assert_awaited_once_with(mocker.sentinel.value)
        assert to_yield is mocker.sentinel.to_yield_from_send

    async def test____ThrowAction____throw_exception(self, mock_generator: MagicMock, mocker: MockerFixture) -> None:
        # Arrange
        exc = ValueError("abc")
        mock_generator.athrow.return_value = mocker.sentinel.to_yield_from_throw
        action: ThrowAction = ThrowAction(exc)

        # Act
        to_yield: Any = await action.asend(mock_generator)

        # Assert
        assert mock_generator.mock_calls == [mocker.call.athrow(exc)]
        mock_generator.athrow.assert_awaited_once_with(exc)
        assert to_yield is mocker.sentinel.to_yield_from_throw

    async def test____ThrowAction____close_generator(self, mock_generator: MagicMock, mocker: MockerFixture) -> None:
        # Arrange
        exc = GeneratorExit()
        action: ThrowAction = ThrowAction(exc)

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
        action: ThrowAction = ThrowAction(exc)
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


@pytest_asyncio.fixture
async def current_asyncgen_hooks() -> AsyncIterator[sys._asyncgen_hooks]:
    current_hooks = sys.get_asyncgen_hooks()
    yield current_hooks
    sys.set_asyncgen_hooks(*current_hooks)


@pytest.mark.asyncio
async def test____anext_without_asyncgen_hook____skips_firstiter_hook(
    current_asyncgen_hooks: sys._asyncgen_hooks,
    mocker: MockerFixture,
) -> None:
    # Arrange
    firstiter_stub = mocker.stub("firstiter_hook")
    firstiter_stub.side_effect = current_asyncgen_hooks.firstiter
    firstiter_stub.return_value = None
    sys.set_asyncgen_hooks(firstiter=firstiter_stub)

    async def async_generator_function() -> AsyncGenerator[int, None]:
        yield 42

    async_generator = async_generator_function()

    # Act
    async with contextlib.aclosing(async_generator):
        value = await anext_without_asyncgen_hook(async_generator)

    # Assert
    assert value == 42
    firstiter_stub.assert_not_called()
    assert sys.get_asyncgen_hooks() == (firstiter_stub, current_asyncgen_hooks.finalizer)


@pytest.mark.asyncio
async def test____anext_without_asyncgen_hook____remove_frame_on_error() -> None:
    # Arrange
    exc = ValueError("abc")

    async def async_generator_function() -> AsyncGenerator[int, None]:
        if False:
            yield 42  # type: ignore[unreachable]
        raise exc

    async_generator = async_generator_function()

    # Act
    with pytest.raises(ValueError):
        await anext_without_asyncgen_hook(async_generator)

    # Assert
    # Top frame in the traceback is the current test function; we don't care
    # about its references
    assert exc.__traceback__ is not None
    assert exc.__traceback__.tb_frame is sys._getframe()
    # The next frame down is the 'async_generator_function' frame
    assert exc.__traceback__.tb_next is not None
    generator_frame = exc.__traceback__.tb_next.tb_frame
    assert generator_frame.f_code.co_name == "async_generator_function"
