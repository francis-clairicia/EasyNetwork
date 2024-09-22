from __future__ import annotations

from asyncio.exceptions import CancelledError
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Literal, assert_never

from easynetwork.exceptions import UnsupportedOperation
from easynetwork.lowlevel.api_async.backend._asyncio.backend import AsyncIOBackend
from easynetwork.lowlevel.api_async.backend.utils import new_builtin_backend
from easynetwork.lowlevel.api_async.transports.abc import (
    AsyncBaseTransport,
    AsyncDatagramReadTransport,
    AsyncDatagramTransport,
    AsyncDatagramWriteTransport,
    AsyncStreamReadTransport,
    AsyncStreamTransport,
    AsyncStreamWriteTransport,
)
from easynetwork.lowlevel.api_async.transports.composite import AsyncStapledDatagramTransport, AsyncStapledStreamTransport

import pytest
import pytest_asyncio

from ...._utils import restore_mock_side_effect
from ...mock_tools import make_transport_mock

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
class BaseAsyncStapledTransportTests:

    async def test____aclose____close_both_transports(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: AsyncBaseTransport,
    ) -> None:
        # Arrange
        assert not stapled_transport.is_closing()

        # Act
        await stapled_transport.aclose()

        # Assert
        assert stapled_transport.is_closing()
        mock_send_transport.aclose.assert_awaited_once_with()
        mock_receive_transport.aclose.assert_awaited_once_with()

    @pytest.mark.parametrize("transport_cancelled", ["send", "receive"])
    async def test____aclose____close_both_transports____even_upon_cancellation(
        self,
        transport_cancelled: Literal["send", "receive"],
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: AsyncBaseTransport,
    ) -> None:
        # Arrange
        match transport_cancelled:
            case "send":
                mock_send_transport.aclose.side_effect = CancelledError
            case "receive":
                mock_receive_transport.aclose.side_effect = CancelledError
            case _:
                assert_never(transport_cancelled)

        # Act
        with pytest.raises(CancelledError):
            await stapled_transport.aclose()

        # Assert
        mock_send_transport.aclose.assert_awaited_once_with()
        mock_receive_transport.aclose.assert_awaited_once_with()

    @pytest.mark.parametrize(
        ["send_transport_is_closing", "receive_transport_is_closing", "expected_state"],
        [
            pytest.param(False, False, False),
            pytest.param(True, False, False),
            pytest.param(False, True, False),
            pytest.param(True, True, True),
        ],
    )
    async def test____is_closing____expected_state(
        self,
        send_transport_is_closing: bool,
        receive_transport_is_closing: bool,
        expected_state: bool,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: AsyncBaseTransport,
    ) -> None:
        # Arrange
        if send_transport_is_closing:
            await mock_send_transport.aclose()
        if receive_transport_is_closing:
            await mock_receive_transport.aclose()

        # Act
        is_closing = stapled_transport.is_closing()

        # Assert
        assert is_closing is expected_state

    async def test____get_backend____default(
        self,
        stapled_transport: AsyncBaseTransport,
        asyncio_backend: AsyncIOBackend,
    ) -> None:
        # Arrange

        # Act & Assert
        assert stapled_transport.backend() is asyncio_backend

    async def test____extra_attributes____both_transports_attributes(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: AsyncBaseTransport,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_send_transport.extra_attributes = {
            mocker.sentinel.send_only_attr: lambda: mocker.sentinel.send_only_value,
            mocker.sentinel.attr_conflict: lambda: mocker.sentinel.send_won,
        }
        mock_receive_transport.extra_attributes = {
            mocker.sentinel.recv_only_attr: lambda: mocker.sentinel.recv_only_value,
            mocker.sentinel.attr_conflict: lambda: mocker.sentinel.recv_won,
        }

        # Act & Assert
        assert stapled_transport.extra(mocker.sentinel.send_only_attr) is mocker.sentinel.send_only_value
        assert stapled_transport.extra(mocker.sentinel.recv_only_attr) is mocker.sentinel.recv_only_value
        assert stapled_transport.extra(mocker.sentinel.attr_conflict) is mocker.sentinel.recv_won


class TestAsyncStapledStreamTransport(BaseAsyncStapledTransportTests):
    @pytest.fixture(params=[AsyncStreamWriteTransport, AsyncStreamTransport])
    @staticmethod
    def mock_send_transport(
        request: pytest.FixtureRequest,
        asyncio_backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=request.param, backend=asyncio_backend)

    @pytest.fixture(params=[AsyncStreamReadTransport, AsyncStreamTransport])
    @staticmethod
    def mock_receive_transport(
        request: pytest.FixtureRequest,
        asyncio_backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=request.param, backend=asyncio_backend)

    @pytest_asyncio.fixture
    @staticmethod
    async def stapled_transport(
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
    ) -> AsyncIterator[AsyncStapledStreamTransport[MagicMock, MagicMock]]:
        transport = AsyncStapledStreamTransport(mock_send_transport, mock_receive_transport)
        mock_send_transport.reset_mock()
        mock_receive_transport.reset_mock()
        async with transport:
            with restore_mock_side_effect(mock_send_transport.aclose), restore_mock_side_effect(mock_receive_transport.aclose):
                yield transport

    async def test____dunder_init___transports_inconsistency_error(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_send_transport.backend.side_effect = [new_builtin_backend("asyncio")]
        mock_receive_transport.backend.side_effect = [new_builtin_backend("asyncio")]

        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^transport backend inconsistency$"):
            _ = AsyncStapledStreamTransport(mock_send_transport, mock_receive_transport)

    async def test____recv____calls_receive_transport_recv(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: AsyncStapledStreamTransport[MagicMock, MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_receive_transport.recv.return_value = mocker.sentinel.recv_result

        # Act
        data = await stapled_transport.recv(mocker.sentinel.recv_bufsize)

        # Assert
        assert data is mocker.sentinel.recv_result
        assert mock_receive_transport.mock_calls == [mocker.call.recv(mocker.sentinel.recv_bufsize)]
        assert mock_send_transport.mock_calls == []

    async def test____recv_into____calls_receive_transport_recv_into(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: AsyncStapledStreamTransport[MagicMock, MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_receive_transport.recv_into.return_value = mocker.sentinel.recv_into_result

        # Act
        nbytes = await stapled_transport.recv_into(mocker.sentinel.recv_buffer)

        # Assert
        assert nbytes is mocker.sentinel.recv_into_result
        assert mock_receive_transport.mock_calls == [mocker.call.recv_into(mocker.sentinel.recv_buffer)]
        assert mock_send_transport.mock_calls == []

    async def test____send_all____calls_send_transport_send_all(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: AsyncStapledStreamTransport[MagicMock, MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_send_transport.send_all.return_value = None

        # Act
        await stapled_transport.send_all(mocker.sentinel.send_data)

        # Assert
        assert mock_send_transport.mock_calls == [mocker.call.send_all(mocker.sentinel.send_data)]
        assert mock_receive_transport.mock_calls == []

    async def test____send_all_from_iterable____calls_send_transport_send_all_from_iterable(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: AsyncStapledStreamTransport[MagicMock, MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_send_transport.send_all_from_iterable.return_value = None

        # Act
        await stapled_transport.send_all_from_iterable(mocker.sentinel.send_data)

        # Assert
        assert mock_send_transport.mock_calls == [mocker.call.send_all_from_iterable(mocker.sentinel.send_data)]
        assert mock_receive_transport.mock_calls == []

    async def test____send_eof____calls_send_transport_send_eof_if_exists_else_aclose(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: AsyncStapledStreamTransport[MagicMock, MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if hasattr(mock_send_transport, "send_eof"):
            mock_send_transport.send_eof.return_value = None

        # Act
        await stapled_transport.send_eof()

        # Assert
        if hasattr(mock_send_transport, "send_eof"):
            assert mock_send_transport.mock_calls == [mocker.call.send_eof()]
        else:
            assert mock_send_transport.mock_calls == [mocker.call.aclose()]
        assert mock_receive_transport.mock_calls == []

    @pytest.mark.parametrize("mock_send_transport", [AsyncStreamTransport], indirect=True)
    @pytest.mark.parametrize("send_eof_error", [UnsupportedOperation, NotImplementedError])
    async def test____send_eof____calls_send_transport_aclos_if_send_eof_is_not_implemented(
        self,
        send_eof_error: type[Exception],
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: AsyncStapledStreamTransport[MagicMock, MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_send_transport.send_eof.side_effect = send_eof_error

        # Act
        await stapled_transport.send_eof()

        # Assert
        assert mock_send_transport.mock_calls == [mocker.call.send_eof(), mocker.call.aclose()]
        assert mock_receive_transport.mock_calls == []


class TestAsyncStapledDatagramTransport(BaseAsyncStapledTransportTests):
    @pytest.fixture(params=[AsyncDatagramWriteTransport, AsyncDatagramTransport])
    @staticmethod
    def mock_send_transport(
        request: pytest.FixtureRequest,
        asyncio_backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=request.param, backend=asyncio_backend)

    @pytest.fixture(params=[AsyncDatagramReadTransport, AsyncDatagramTransport])
    @staticmethod
    def mock_receive_transport(
        request: pytest.FixtureRequest,
        asyncio_backend: AsyncIOBackend,
        mocker: MockerFixture,
    ) -> MagicMock:
        return make_transport_mock(mocker=mocker, spec=request.param, backend=asyncio_backend)

    @pytest_asyncio.fixture
    @staticmethod
    async def stapled_transport(
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
    ) -> AsyncIterator[AsyncStapledDatagramTransport[MagicMock, MagicMock]]:
        transport = AsyncStapledDatagramTransport(mock_send_transport, mock_receive_transport)
        mock_send_transport.reset_mock()
        mock_receive_transport.reset_mock()
        async with transport:
            with restore_mock_side_effect(mock_send_transport.aclose), restore_mock_side_effect(mock_receive_transport.aclose):
                yield transport

    async def test____dunder_init___transports_inconsistency_error(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
    ) -> None:
        # Arrange
        mock_send_transport.backend.side_effect = [new_builtin_backend("asyncio")]
        mock_receive_transport.backend.side_effect = [new_builtin_backend("asyncio")]

        # Act & Assert
        with pytest.raises(RuntimeError, match=r"^transport backend inconsistency$"):
            _ = AsyncStapledDatagramTransport(mock_send_transport, mock_receive_transport)

    async def test____recv____calls_receive_transport_recv(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: AsyncStapledDatagramTransport[MagicMock, MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_receive_transport.recv.return_value = mocker.sentinel.recv_result

        # Act
        data = await stapled_transport.recv()

        # Assert
        assert data is mocker.sentinel.recv_result
        assert mock_receive_transport.mock_calls == [mocker.call.recv()]
        assert mock_send_transport.mock_calls == []

    async def test____send____calls_send_transport_send(
        self,
        mock_send_transport: MagicMock,
        mock_receive_transport: MagicMock,
        stapled_transport: AsyncStapledDatagramTransport[MagicMock, MagicMock],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_send_transport.send.return_value = None

        # Act
        await stapled_transport.send(mocker.sentinel.send_data)

        # Assert
        assert mock_send_transport.mock_calls == [mocker.call.send(mocker.sentinel.send_data)]
        assert mock_receive_transport.mock_calls == []
