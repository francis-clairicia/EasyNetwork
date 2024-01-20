from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import ssl
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, NoReturn

from easynetwork.exceptions import UnsupportedOperation
from easynetwork.lowlevel.api_async.transports.abc import AsyncBufferedStreamReadTransport, AsyncListener, AsyncStreamTransport
from easynetwork.lowlevel.api_async.transports.tls import AsyncTLSListener, AsyncTLSStreamTransport
from easynetwork.lowlevel.constants import NOT_CONNECTED_SOCKET_ERRNOS, SSL_SHUTDOWN_TIMEOUT as DEFAULT_SSL_SHUTDOWN_TIMEOUT
from easynetwork.lowlevel.socket import TLSAttribute

import pytest

from ...._utils import make_async_recv_into_side_effect as make_recv_into_side_effect

if TYPE_CHECKING:
    from unittest.mock import AsyncMock, MagicMock

    from pytest_mock import MockerFixture


class _AsyncBufferedStreamTransport(AsyncStreamTransport, AsyncBufferedStreamReadTransport):
    __slots__ = ()


@pytest.mark.asyncio
class TestAsyncTLSStreamTransport:
    @pytest.fixture
    @staticmethod
    def mock_wrapped_transport_extra_attributes() -> dict[Any, Callable[[], Any]]:
        return {}

    @pytest.fixture(params=["data", "buffered"])
    @staticmethod
    def mock_wrapped_transport(
        request: pytest.FixtureRequest,
        mock_wrapped_transport_extra_attributes: dict[Any, Callable[[], Any]],
        mocker: MockerFixture,
    ) -> MagicMock:
        match request.param:
            case "data":
                mock_wrapped_transport = mocker.NonCallableMagicMock(spec=AsyncStreamTransport)
            case "buffered":
                mock_wrapped_transport = mocker.NonCallableMagicMock(spec=_AsyncBufferedStreamTransport)
            case _:
                pytest.fail("Invalid fixture param")

        mock_wrapped_transport.extra_attributes = mock_wrapped_transport_extra_attributes
        mock_wrapped_transport.is_closing.return_value = False
        return mock_wrapped_transport

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_ssl_context(mock_ssl_context: MagicMock, mock_ssl_object: MagicMock, mocker: MockerFixture) -> MagicMock:
        mock_ssl_context.wrap_bio.return_value = mock_ssl_object
        mock_ssl_object.do_handshake.return_value = None
        mock_ssl_object.context = mock_ssl_context
        mock_ssl_object.getpeercert.return_value = mocker.sentinel.peercert
        mock_ssl_object.cipher.return_value = mocker.sentinel.cipher
        mock_ssl_object.compression.return_value = mocker.sentinel.compression
        mock_ssl_object.version.return_value = mocker.sentinel.tls_version
        return mock_ssl_context

    @pytest.fixture
    @staticmethod
    def read_bio() -> ssl.MemoryBIO:
        return ssl.MemoryBIO()

    @pytest.fixture
    @staticmethod
    def write_bio() -> ssl.MemoryBIO:
        return ssl.MemoryBIO()

    @pytest.fixture
    @staticmethod
    def standard_compatible(request: pytest.FixtureRequest) -> bool:
        return getattr(request, "param", True)

    @pytest.fixture
    @staticmethod
    def shutdown_timeout(request: pytest.FixtureRequest) -> float:
        return getattr(request, "param", 987654321)

    @pytest.fixture
    @staticmethod
    def tls_transport(
        mock_wrapped_transport: MagicMock,
        mock_ssl_object: MagicMock,
        standard_compatible: bool,
        shutdown_timeout: float,
        read_bio: ssl.MemoryBIO,
        write_bio: ssl.MemoryBIO,
    ) -> AsyncTLSStreamTransport:
        return AsyncTLSStreamTransport(
            _transport=mock_wrapped_transport,
            _standard_compatible=standard_compatible,
            _shutdown_timeout=shutdown_timeout,
            _ssl_object=mock_ssl_object,
            _read_bio=read_bio,
            _write_bio=write_bio,
        )

    @pytest.fixture
    @staticmethod
    def mock_tls_transport_retry(mocker: MockerFixture) -> AsyncMock:
        side_effect: Callable[..., Any] = lambda ssl_object_method, *args: ssl_object_method(*args)
        return mocker.patch.object(AsyncTLSStreamTransport, "_retry_ssl_method", side_effect=side_effect)

    async def test____wrap____default(
        self,
        mock_wrapped_transport: MagicMock,
        mock_wrapped_transport_extra_attributes: dict[Any, Callable[[], Any]],
        mock_tls_transport_retry: AsyncMock,
        mock_ssl_context: MagicMock,
        mock_ssl_object: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_wrapped_transport_extra_attributes[mocker.sentinel.attr_1] = lambda: mocker.sentinel.value_1
        mock_wrapped_transport_extra_attributes[mocker.sentinel.attr_2] = lambda: mocker.sentinel.value_2

        # Act
        tls_transport = await AsyncTLSStreamTransport.wrap(
            mock_wrapped_transport, mock_ssl_context, server_hostname="server_hostname"
        )

        # Assert
        ## Instantiation
        assert type(tls_transport) is AsyncTLSStreamTransport
        mock_ssl_context.wrap_bio.assert_called_once_with(
            mocker.ANY,  # read_bio
            mocker.ANY,  # write_bio
            server_side=False,
            server_hostname="server_hostname",
            session=None,
        )
        mock_tls_transport_retry.assert_awaited_once_with(mock_ssl_object.do_handshake)
        assert mock_ssl_object.mock_calls == [mocker.call.do_handshake(), mocker.call.getpeercert()]
        ## Attributes
        assert tls_transport._shutdown_timeout == DEFAULT_SSL_SHUTDOWN_TIMEOUT
        assert tls_transport.extra(mocker.sentinel.attr_1) is mocker.sentinel.value_1
        assert tls_transport.extra(mocker.sentinel.attr_2) is mocker.sentinel.value_2
        assert tls_transport.extra(TLSAttribute.sslcontext) is mock_ssl_context
        assert tls_transport.extra(TLSAttribute.peercert) is mocker.sentinel.peercert
        assert tls_transport.extra(TLSAttribute.cipher) is mocker.sentinel.cipher
        assert tls_transport.extra(TLSAttribute.compression) is mocker.sentinel.compression
        assert tls_transport.extra(TLSAttribute.tls_version) is mocker.sentinel.tls_version
        assert tls_transport.extra(TLSAttribute.standard_compatible) is True

    @pytest.mark.parametrize("server_hostname", [None, "server_hostname"], ids=lambda p: f"server_hostname=={p}")
    @pytest.mark.parametrize("server_side", [True, False], ids=lambda p: f"server_side=={p}")
    @pytest.mark.parametrize("session", [None, "session"], ids=lambda p: f"session=={p}")
    @pytest.mark.parametrize("standard_compatible", [True, False], ids=lambda p: f"standard_compatible=={p}")
    @pytest.mark.parametrize("handshake_timeout", [123465789], ids=lambda p: f"handshake_timeout=={p}")
    @pytest.mark.parametrize("shutdown_timeout", [987654321], ids=lambda p: f"shutdown_timeout=={p}")
    async def test____wrap____with_parameters(
        self,
        server_hostname: str | None,
        server_side: bool,
        session: Any | None,
        standard_compatible: bool,
        handshake_timeout: float,
        shutdown_timeout: float,
        mock_wrapped_transport: MagicMock,
        mock_wrapped_transport_extra_attributes: dict[Any, Callable[[], Any]],
        mock_tls_transport_retry: AsyncMock,
        mock_ssl_context: MagicMock,
        mock_ssl_object: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        if session is not None:
            session = getattr(mocker.sentinel, session)
        mock_wrapped_transport_extra_attributes[mocker.sentinel.attr_1] = lambda: mocker.sentinel.value_1
        mock_wrapped_transport_extra_attributes[mocker.sentinel.attr_2] = lambda: mocker.sentinel.value_2

        # Act
        tls_transport = await AsyncTLSStreamTransport.wrap(
            mock_wrapped_transport,
            mock_ssl_context,
            handshake_timeout=handshake_timeout,
            shutdown_timeout=shutdown_timeout,
            server_hostname=server_hostname,
            server_side=server_side,
            standard_compatible=standard_compatible,
            session=session,
        )

        # Assert
        ## Instantiation
        assert type(tls_transport) is AsyncTLSStreamTransport
        mock_ssl_context.wrap_bio.assert_called_once_with(
            mocker.ANY,  # read_bio
            mocker.ANY,  # write_bio
            server_side=server_side,
            server_hostname=server_hostname,
            session=session,
        )
        mock_tls_transport_retry.assert_awaited_once_with(mock_ssl_object.do_handshake)
        assert mock_ssl_object.mock_calls == [mocker.call.do_handshake(), mocker.call.getpeercert()]
        assert not mock_wrapped_transport.mock_calls
        ## Attributes
        assert tls_transport._shutdown_timeout == shutdown_timeout
        assert tls_transport.extra(mocker.sentinel.attr_1) is mocker.sentinel.value_1
        assert tls_transport.extra(mocker.sentinel.attr_2) is mocker.sentinel.value_2
        assert tls_transport.extra(TLSAttribute.sslcontext) is mock_ssl_context
        assert tls_transport.extra(TLSAttribute.peercert) is mocker.sentinel.peercert
        assert tls_transport.extra(TLSAttribute.cipher) is mocker.sentinel.cipher
        assert tls_transport.extra(TLSAttribute.compression) is mocker.sentinel.compression
        assert tls_transport.extra(TLSAttribute.tls_version) is mocker.sentinel.tls_version
        assert tls_transport.extra(TLSAttribute.standard_compatible) is standard_compatible

    @pytest.mark.parametrize(
        ["server_hostname", "expected_server_side"],
        [
            pytest.param(None, True, id="server_hostname==None"),
            pytest.param("hostname", False, id="server_hostname=='hostname'"),
        ],
    )
    @pytest.mark.usefixtures("mock_tls_transport_retry")
    async def test____wrap____server_side____guess_according_to_server_hostname(
        self,
        server_hostname: str | None,
        expected_server_side: bool,
        mock_wrapped_transport: MagicMock,
        mock_ssl_context: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange

        # Act
        _ = await AsyncTLSStreamTransport.wrap(
            mock_wrapped_transport,
            mock_ssl_context,
            server_hostname=server_hostname,
        )

        # Assert
        mock_ssl_context.wrap_bio.assert_called_once_with(
            mocker.ANY,  # read_bio
            mocker.ANY,  # write_bio
            server_side=expected_server_side,
            server_hostname=server_hostname,
            session=None,
        )

    async def test____wrap____handshake_timeout(
        self,
        mock_wrapped_transport: MagicMock,
        mock_tls_transport_retry: AsyncMock,
        mock_ssl_context: MagicMock,
        mock_ssl_object: MagicMock,
    ) -> None:
        # Arrange
        async def retry_side_effect(ssl_object_method: Callable[..., Any], *args: Any) -> Any:
            await asyncio.sleep(5)
            return ssl_object_method(*args)

        mock_tls_transport_retry.side_effect = retry_side_effect

        # Act & Assert
        with pytest.raises(TimeoutError):
            _ = await AsyncTLSStreamTransport.wrap(
                mock_wrapped_transport, mock_ssl_context, handshake_timeout=1, server_side=False
            )

        mock_ssl_object.do_handshake.assert_not_called()
        mock_wrapped_transport.aclose.assert_awaited_once_with()

    @pytest.mark.usefixtures("mock_tls_transport_retry")
    async def test____wrap____handshake_failed(
        self,
        mock_wrapped_transport: MagicMock,
        mock_ssl_context: MagicMock,
        mock_ssl_object: MagicMock,
    ) -> None:
        # Arrange
        mock_ssl_object.do_handshake.side_effect = ssl.SSLError(ssl.SSL_ERROR_SSL, "SSL_ERROR_SSL")

        # Act & Assert
        with pytest.raises(ssl.SSLError):
            _ = await AsyncTLSStreamTransport.wrap(mock_wrapped_transport, mock_ssl_context, server_side=False)

        mock_wrapped_transport.aclose.assert_awaited_once_with()

    @pytest.mark.usefixtures("mock_tls_transport_retry")
    async def test____wrap____certificate_error(
        self,
        mock_wrapped_transport: MagicMock,
        mock_ssl_context: MagicMock,
        mock_ssl_object: MagicMock,
    ) -> None:
        # Arrange
        mock_ssl_object.getpeercert.side_effect = ssl.CertificateError

        # Act & Assert
        with pytest.raises(ssl.CertificateError):
            _ = await AsyncTLSStreamTransport.wrap(mock_wrapped_transport, mock_ssl_context, server_side=False)

        mock_wrapped_transport.aclose.assert_awaited_once_with()

    @pytest.mark.parametrize("standard_compatible", [False, True], indirect=True, ids=lambda p: f"standard_compatible=={p}")
    async def test____aclose____close_transport(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_tls_transport_retry: AsyncMock,
        mock_wrapped_transport: MagicMock,
        mock_ssl_object: MagicMock,
        standard_compatible: bool,
        read_bio: ssl.MemoryBIO,
        write_bio: ssl.MemoryBIO,
    ) -> None:
        # Arrange
        assert not tls_transport.is_closing()

        # Act
        await tls_transport.aclose()

        # Assert
        assert tls_transport.is_closing()
        if standard_compatible:
            mock_tls_transport_retry.assert_awaited_once_with(mock_ssl_object.unwrap)
            mock_ssl_object.unwrap.assert_called_once_with()
            assert read_bio.eof
            assert write_bio.eof
        else:
            mock_tls_transport_retry.assert_not_called()
            mock_ssl_object.unwrap.assert_not_called()
            assert not read_bio.eof
            assert not write_bio.eof
        mock_wrapped_transport.aclose.assert_awaited_once_with()

    @pytest.mark.parametrize("standard_compatible", [True], indirect=True, ids=lambda p: f"standard_compatible=={p}")
    @pytest.mark.parametrize("shutdown_timeout", [1], indirect=True, ids=lambda p: f"shutdown_timeout=={p}")
    async def test____aclose____shutdown_timeout(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_tls_transport_retry: AsyncMock,
        mock_wrapped_transport: MagicMock,
        mock_ssl_object: MagicMock,
        read_bio: ssl.MemoryBIO,
        write_bio: ssl.MemoryBIO,
    ) -> None:
        # Arrange
        async def retry_side_effect(ssl_object_method: Callable[..., Any], *args: Any) -> Any:
            await asyncio.sleep(5)
            return ssl_object_method(*args)

        mock_tls_transport_retry.side_effect = retry_side_effect

        # Act
        await tls_transport.aclose()

        # Assert
        mock_tls_transport_retry.assert_awaited_once_with(mock_ssl_object.unwrap)
        assert not read_bio.eof
        assert not write_bio.eof
        mock_wrapped_transport.aclose.assert_awaited_once_with()

    async def test____recv____default(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_tls_transport_retry: AsyncMock,
        mock_ssl_object: MagicMock,
    ) -> None:
        # Arrange
        mock_ssl_object.read.return_value = b"decrypted-data"

        # Act
        data = await tls_transport.recv(123456)

        # Assert
        assert data == b"decrypted-data"
        mock_tls_transport_retry.assert_awaited_once_with(mock_ssl_object.read, 123456)
        mock_ssl_object.read.assert_called_once_with(123456)

    async def test____recv____null_buffer(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_tls_transport_retry: AsyncMock,
        mock_ssl_object: MagicMock,
    ) -> None:
        # Arrange
        mock_ssl_object.read.return_value = b""

        # Act
        data = await tls_transport.recv(0)

        # Assert
        assert data == b""
        mock_tls_transport_retry.assert_awaited_once_with(mock_ssl_object.read, 0)
        mock_ssl_object.read.assert_called_once_with(0)

    @pytest.mark.parametrize("standard_compatible", [False, True], indirect=True, ids=lambda p: f"standard_compatible=={p}")
    @pytest.mark.usefixtures("mock_tls_transport_retry")
    async def test____recv____SSLZeroReturnError(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_ssl_object: MagicMock,
    ) -> None:
        # Arrange
        mock_ssl_object.read.side_effect = ssl.SSLZeroReturnError

        # Act
        data = await tls_transport.recv(123456)

        # Assert
        assert data == b""

    @pytest.mark.parametrize("standard_compatible", [False, True], indirect=True, ids=lambda p: f"standard_compatible=={p}")
    @pytest.mark.usefixtures("mock_tls_transport_retry")
    async def test____recv____ragged_eof(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_ssl_object: MagicMock,
        standard_compatible: bool,
    ) -> None:
        # Arrange
        mock_ssl_object.read.side_effect = ssl.SSLEOFError(ssl.SSL_ERROR_EOF, "SSL_ERROR_EOF")

        # Act & Assert
        if standard_compatible:
            with pytest.raises(ssl.SSLEOFError):
                await tls_transport.recv(123456)
        else:
            data = await tls_transport.recv(123456)
            assert data == b""

    @pytest.mark.parametrize("standard_compatible", [False, True], indirect=True, ids=lambda p: f"standard_compatible=={p}")
    @pytest.mark.usefixtures("mock_tls_transport_retry")
    async def test____recv____unrelated_ssl_error(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_ssl_object: MagicMock,
    ) -> None:
        # Arrange
        mock_ssl_object.read.side_effect = ssl.SSLError(ssl.SSL_ERROR_SSL, "SSL_ERROR_SSL")

        # Act & Assert
        with pytest.raises(ssl.SSLError):
            _ = await tls_transport.recv(123456)

    async def test____recv_into____default(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_tls_transport_retry: AsyncMock,
        mock_ssl_object: MagicMock,
    ) -> None:
        # Arrange
        mock_ssl_object.read.return_value = 42
        buffer = bytearray(1234)

        # Act
        nbytes = await tls_transport.recv_into(buffer)

        # Assert
        assert nbytes == 42
        mock_tls_transport_retry.assert_awaited_once_with(mock_ssl_object.read, 1234, buffer)
        mock_ssl_object.read.assert_called_once_with(1234, buffer)

    async def test____recv_into____null_buffer(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_tls_transport_retry: AsyncMock,
        mock_ssl_object: MagicMock,
    ) -> None:
        # Arrange
        mock_ssl_object.read.return_value = 0
        buffer = bytearray(0)

        # Act
        nbytes = await tls_transport.recv_into(buffer)

        # Assert
        assert nbytes == 0
        mock_tls_transport_retry.assert_awaited_once_with(mock_ssl_object.read, 1024, buffer)
        mock_ssl_object.read.assert_called_once_with(1024, buffer)

    @pytest.mark.parametrize("standard_compatible", [False, True], indirect=True, ids=lambda p: f"standard_compatible=={p}")
    @pytest.mark.usefixtures("mock_tls_transport_retry")
    async def test____recv_into____SSLZeroReturnError(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_ssl_object: MagicMock,
    ) -> None:
        # Arrange
        mock_ssl_object.read.side_effect = ssl.SSLZeroReturnError
        buffer = bytearray(1234)

        # Act
        nbytes = await tls_transport.recv_into(buffer)

        # Assert
        assert nbytes == 0

    @pytest.mark.parametrize("standard_compatible", [False, True], indirect=True, ids=lambda p: f"standard_compatible=={p}")
    @pytest.mark.usefixtures("mock_tls_transport_retry")
    async def test____recv_into____ragged_eof(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_ssl_object: MagicMock,
        standard_compatible: bool,
    ) -> None:
        # Arrange
        mock_ssl_object.read.side_effect = ssl.SSLEOFError(ssl.SSL_ERROR_EOF, "SSL_ERROR_EOF")
        buffer = bytearray(1234)

        # Act & Assert
        if standard_compatible:
            with pytest.raises(ssl.SSLEOFError):
                await tls_transport.recv_into(buffer)
        else:
            nbytes = await tls_transport.recv_into(buffer)
            assert nbytes == 0

    @pytest.mark.parametrize("standard_compatible", [False, True], indirect=True, ids=lambda p: f"standard_compatible=={p}")
    @pytest.mark.usefixtures("mock_tls_transport_retry")
    async def test____recv_into____unrelated_ssl_error(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_ssl_object: MagicMock,
    ) -> None:
        # Arrange
        mock_ssl_object.read.side_effect = ssl.SSLError(ssl.SSL_ERROR_SSL, "SSL_ERROR_SSL")
        buffer = bytearray(1234)

        # Act & Assert
        with pytest.raises(ssl.SSLError):
            _ = await tls_transport.recv_into(buffer)

    async def test____send_all____default(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_tls_transport_retry: AsyncMock,
        mock_ssl_object: MagicMock,
    ) -> None:
        # Arrange
        mock_ssl_object.write.side_effect = lambda data: memoryview(data).nbytes

        # Act
        await tls_transport.send_all(b"decrypted-data")

        # Assert
        mock_tls_transport_retry.assert_awaited_once_with(mock_ssl_object.write, b"decrypted-data")
        mock_ssl_object.write.assert_called_once_with(b"decrypted-data")

    async def test____send_all____null_buffer(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_tls_transport_retry: AsyncMock,
        mock_ssl_object: MagicMock,
    ) -> None:
        # Arrange
        mock_ssl_object.write.side_effect = lambda data: memoryview(data).nbytes

        # Act
        await tls_transport.send_all(b"")

        # Assert
        mock_tls_transport_retry.assert_awaited_once_with(mock_ssl_object.write, b"")
        mock_ssl_object.write.assert_called_once_with(b"")

    @pytest.mark.parametrize("standard_compatible", [False, True], indirect=True, ids=lambda p: f"standard_compatible=={p}")
    @pytest.mark.usefixtures("mock_tls_transport_retry")
    async def test____send_all____SSLZeroReturnError(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_ssl_object: MagicMock,
    ) -> None:
        # Arrange
        mock_ssl_object.write.side_effect = ssl.SSLZeroReturnError

        # Act & Assert
        with pytest.raises(ConnectionResetError):
            await tls_transport.send_all(b"decrypted-data")

    @pytest.mark.parametrize("standard_compatible", [False, True], indirect=True, ids=lambda p: f"standard_compatible=={p}")
    @pytest.mark.usefixtures("mock_tls_transport_retry")
    async def test____send_all____ragged_eof(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_ssl_object: MagicMock,
    ) -> None:
        # Arrange
        mock_ssl_object.write.side_effect = ssl.SSLEOFError(ssl.SSL_ERROR_EOF, "SSL_ERROR_EOF")

        # Act & Assert
        with pytest.raises(ssl.SSLEOFError):
            await tls_transport.send_all(b"decrypted-data")

    @pytest.mark.parametrize("standard_compatible", [False, True], indirect=True, ids=lambda p: f"standard_compatible=={p}")
    @pytest.mark.usefixtures("mock_tls_transport_retry")
    async def test____send_all____unrelated_ssl_error(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_ssl_object: MagicMock,
    ) -> None:
        # Arrange
        mock_ssl_object.write.side_effect = ssl.SSLError(ssl.SSL_ERROR_SSL, "SSL_ERROR_SSL")

        # Act & Assert
        with pytest.raises(ssl.SSLError):
            await tls_transport.send_all(b"decrypted-data")

    async def test____send_eof____default(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_tls_transport_retry: AsyncMock,
        mock_wrapped_transport: MagicMock,
        mock_ssl_object: MagicMock,
        read_bio: ssl.MemoryBIO,
        write_bio: ssl.MemoryBIO,
    ) -> None:
        # Arrange

        # Act
        with pytest.raises(UnsupportedOperation):
            await tls_transport.send_eof()

        # Assert
        assert not mock_tls_transport_retry.mock_calls
        assert not mock_wrapped_transport.mock_calls
        assert not mock_ssl_object.mock_calls
        assert not read_bio.eof
        assert not write_bio.eof

    @pytest.mark.parametrize("pending_write", [b"", b"encrypted-data\n"], ids=lambda p: f"pending_write=={p!r}")
    async def test____retry____default(
        self,
        tls_transport: AsyncTLSStreamTransport,
        pending_write: bytes,
        mock_wrapped_transport: MagicMock,
        # read_bio: ssl.MemoryBIO,
        write_bio: ssl.MemoryBIO,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_wrapped_transport.send_all.return_value = None

        def ssl_object_method_side_effect(*args: Any) -> Any:
            write_bio.write(pending_write)
            return mocker.sentinel.result

        ssl_object_method = mocker.MagicMock(side_effect=ssl_object_method_side_effect)

        # Act
        result = await tls_transport._retry_ssl_method(ssl_object_method, mocker.sentinel.arg1, mocker.sentinel.arg2)

        # Assert
        ssl_object_method.assert_called_once_with(mocker.sentinel.arg1, mocker.sentinel.arg2)
        if pending_write:
            mock_wrapped_transport.send_all.assert_awaited_once_with(pending_write)
        else:
            mock_wrapped_transport.send_all.assert_not_called()
        assert result is mocker.sentinel.result

    async def test____retry____SSLWantWriteError(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_wrapped_transport: MagicMock,
        # read_bio: ssl.MemoryBIO,
        write_bio: ssl.MemoryBIO,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_wrapped_transport.send_all.return_value = None

        def ssl_object_method_side_effect(queue: list[bytes]) -> Any:
            if queue:
                write_bio.write(queue.pop(0))
                raise ssl.SSLWantWriteError
            return mocker.sentinel.result

        ssl_object_method = mocker.MagicMock(side_effect=ssl_object_method_side_effect)

        # Act
        result = await tls_transport._retry_ssl_method(ssl_object_method, [b"encrypted-data\n"])

        # Assert
        assert ssl_object_method.call_count == 2
        mock_wrapped_transport.send_all.assert_awaited_once_with(b"encrypted-data\n")
        assert result is mocker.sentinel.result

    @pytest.mark.parametrize("pending_write", [b"", b"encrypted-data\n"], ids=lambda p: f"pending_write=={p!r}")
    async def test____retry____SSLWantReadError(
        self,
        pending_write: bytes,
        tls_transport: AsyncTLSStreamTransport,
        mock_wrapped_transport: MagicMock,
        read_bio: ssl.MemoryBIO,
        write_bio: ssl.MemoryBIO,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_wrapped_transport.send_all.return_value = None
        mock_wrapped_transport.recv.side_effect = [b"encrypted-received-data\n"]
        with contextlib.suppress(AttributeError):
            mock_wrapped_transport.recv_into.side_effect = make_recv_into_side_effect([b"encrypted-received-data\n"])

        def ssl_object_method_side_effect() -> Any:
            write_bio.write(pending_write)
            if not (data := read_bio.read()):
                raise ssl.SSLWantReadError
            return data.replace(b"encrypted-", b"decrypted-").rstrip()

        ssl_object_method = mocker.MagicMock(side_effect=ssl_object_method_side_effect)

        # Act
        result = await tls_transport._retry_ssl_method(ssl_object_method)

        # Assert
        assert ssl_object_method.call_count == 2
        if pending_write:
            assert mock_wrapped_transport.send_all.await_args_list == [mocker.call(pending_write) for _ in range(2)]
        else:
            mock_wrapped_transport.send_all.assert_not_called()
        if hasattr(mock_wrapped_transport, "recv_into"):
            mock_wrapped_transport.recv_into.assert_awaited_once_with(mocker.ANY)
            mock_wrapped_transport.recv.assert_not_called()
        else:
            mock_wrapped_transport.recv.assert_awaited_once_with(mocker.ANY)
        assert result == b"decrypted-received-data"

    async def test____retry____SSLWantReadError____unexpected_eof(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_wrapped_transport: MagicMock,
        read_bio: ssl.MemoryBIO,
        write_bio: ssl.MemoryBIO,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_wrapped_transport.send_all.return_value = None
        mock_wrapped_transport.recv.side_effect = [b""]
        with contextlib.suppress(AttributeError):
            mock_wrapped_transport.recv_into.side_effect = make_recv_into_side_effect([b""])

        def ssl_object_method_side_effect() -> Any:
            if not (data := read_bio.read()):
                if read_bio.eof:
                    raise ssl.SSLEOFError(ssl.SSL_ERROR_EOF, "SSL_ERROR_EOF")
                raise ssl.SSLWantReadError
            return data.replace(b"encrypted-", b"decrypted-").rstrip()

        ssl_object_method = mocker.MagicMock(side_effect=ssl_object_method_side_effect)

        # Act & Assert
        with pytest.raises(ssl.SSLEOFError):
            await tls_transport._retry_ssl_method(ssl_object_method)

        assert ssl_object_method.call_count == 2
        assert read_bio.eof
        assert write_bio.eof

    async def test____retry____SSLWantReadError____unexpected_OSError(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_wrapped_transport: MagicMock,
        read_bio: ssl.MemoryBIO,
        write_bio: ssl.MemoryBIO,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_wrapped_transport.send_all.return_value = None
        mock_wrapped_transport.recv.side_effect = BrokenPipeError()
        with contextlib.suppress(AttributeError):
            mock_wrapped_transport.recv_into.side_effect = BrokenPipeError()

        def ssl_object_method_side_effect() -> Any:
            if not (data := read_bio.read()):
                if read_bio.eof:
                    raise ssl.SSLEOFError(ssl.SSL_ERROR_EOF, "SSL_ERROR_EOF")
                raise ssl.SSLWantReadError
            return data.replace(b"encrypted-", b"decrypted-").rstrip()

        ssl_object_method = mocker.MagicMock(side_effect=ssl_object_method_side_effect)

        # Act & Assert
        with pytest.raises(BrokenPipeError):
            await tls_transport._retry_ssl_method(ssl_object_method)

        assert ssl_object_method.call_count == 1
        assert read_bio.eof
        assert write_bio.eof

    async def test____retry____unrelated_ssl_error(
        self,
        tls_transport: AsyncTLSStreamTransport,
        mock_wrapped_transport: MagicMock,
        read_bio: ssl.MemoryBIO,
        write_bio: ssl.MemoryBIO,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_wrapped_transport.send_all.return_value = None
        ssl_object_method = mocker.MagicMock(side_effect=ssl.SSLError(ssl.SSL_ERROR_SSL, "SSL_ERROR_SSL"))

        # Act & Assert
        with pytest.raises(ssl.SSLError):
            await tls_transport._retry_ssl_method(ssl_object_method)

        assert not mock_wrapped_transport.mock_calls
        assert ssl_object_method.call_count == 1
        assert read_bio.eof
        assert write_bio.eof


@pytest.mark.asyncio
class TestAsyncTLSListener:
    @pytest.fixture
    @staticmethod
    def mock_wrapped_client_transport(mocker: MockerFixture) -> MagicMock:
        mock_wrapped_client_transport = mocker.NonCallableMagicMock(spec=AsyncStreamTransport)
        mock_wrapped_client_transport.extra_attributes = {}
        mock_wrapped_client_transport.is_closing.return_value = False
        return mock_wrapped_client_transport

    @pytest.fixture
    @staticmethod
    def mock_tls_transport(mocker: MockerFixture) -> MagicMock:
        mock_tls_transport = mocker.NonCallableMagicMock(spec=AsyncTLSStreamTransport)
        mock_tls_transport.extra_attributes = {}
        mock_tls_transport.is_closing.return_value = False
        return mock_tls_transport

    @pytest.fixture
    @staticmethod
    def mock_wrapped_listener_extra_attributes() -> dict[Any, Callable[[], Any]]:
        return {}

    @pytest.fixture
    @staticmethod
    def mock_wrapped_listener(
        mock_wrapped_listener_extra_attributes: dict[Any, Callable[[], Any]],
        mock_wrapped_client_transport: MagicMock,
        mocker: MockerFixture,
    ) -> MagicMock:
        async def serve_side_effect(handler: Callable[..., Any], task_group: Any) -> NoReturn:
            await handler(mock_wrapped_client_transport)
            raise asyncio.CancelledError

        mock_wrapped_listener = mocker.NonCallableMagicMock(spec=AsyncListener)
        mock_wrapped_listener.extra_attributes = mock_wrapped_listener_extra_attributes
        mock_wrapped_listener.is_closing.return_value = False
        mock_wrapped_listener.serve.side_effect = serve_side_effect
        return mock_wrapped_listener

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_tls_wrap_transport(mock_tls_transport: MagicMock, mocker: MockerFixture) -> AsyncMock:
        return mocker.patch.object(AsyncTLSStreamTransport, "wrap", autospec=True, return_value=mock_tls_transport)

    @pytest.fixture
    @staticmethod
    def standard_compatible(request: pytest.FixtureRequest) -> bool:
        return getattr(request, "param", True)

    @pytest.fixture
    @staticmethod
    def handshake_timeout(request: pytest.FixtureRequest) -> float | None:
        return getattr(request, "param", None)

    @pytest.fixture
    @staticmethod
    def shutdown_timeout(request: pytest.FixtureRequest) -> float | None:
        return getattr(request, "param", None)

    @pytest.fixture
    @staticmethod
    def tls_listener(
        mock_wrapped_listener: MagicMock,
        mock_ssl_context: MagicMock,
        standard_compatible: bool,
        handshake_timeout: float | None,
        shutdown_timeout: float | None,
    ) -> AsyncTLSListener:
        return AsyncTLSListener(
            mock_wrapped_listener,
            mock_ssl_context,
            handshake_timeout=handshake_timeout,
            shutdown_timeout=shutdown_timeout,
            standard_compatible=standard_compatible,
        )

    @pytest.mark.parametrize("standard_compatible", [False, True], indirect=True, ids=lambda p: f"standard_compatible=={p}")
    async def test____extra_attributes____default(
        self,
        tls_listener: AsyncTLSListener,
        standard_compatible: bool,
        mock_ssl_context: MagicMock,
        mock_wrapped_listener_extra_attributes: dict[Any, Callable[[], Any]],
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        mock_wrapped_listener_extra_attributes[mocker.sentinel.attr_1] = lambda: mocker.sentinel.value_1
        mock_wrapped_listener_extra_attributes[mocker.sentinel.attr_2] = lambda: mocker.sentinel.value_2

        # Act & Assert
        assert tls_listener.extra(mocker.sentinel.attr_1) is mocker.sentinel.value_1
        assert tls_listener.extra(mocker.sentinel.attr_2) is mocker.sentinel.value_2
        assert tls_listener.extra(TLSAttribute.sslcontext) is mock_ssl_context
        assert tls_listener.extra(TLSAttribute.standard_compatible) is standard_compatible

    @pytest.mark.parametrize("transport_is_closing", [False, True], ids=lambda p: f"transport_is_closing=={p}")
    async def test____is_closing____returns_wrapped_listener_state(
        self,
        transport_is_closing: bool,
        tls_listener: AsyncTLSListener,
        mock_wrapped_listener: MagicMock,
    ) -> None:
        # Arrange
        mock_wrapped_listener.is_closing.return_value = transport_is_closing

        # Act
        state = tls_listener.is_closing()

        # Assert
        assert state is transport_is_closing

    async def test____aclose____close_wrapped_listener(
        self,
        tls_listener: AsyncTLSListener,
        mock_wrapped_listener: MagicMock,
    ) -> None:
        # Arrange

        # Act
        await tls_listener.aclose()

        # Assert
        mock_wrapped_listener.aclose.assert_awaited_once_with()

    @pytest.mark.parametrize("external_group", [True, False], ids=lambda p: f"external_group=={p}")
    async def test____serve____wrap_client_stream(
        self,
        external_group: bool,
        tls_listener: AsyncTLSListener,
        mock_wrapped_listener: MagicMock,
        mock_wrapped_client_transport: MagicMock,
        mock_tls_wrap_transport: AsyncMock,
        mock_tls_transport: MagicMock,
        mock_ssl_context: MagicMock,
        handshake_timeout: float,
        shutdown_timeout: float,
        standard_compatible: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        from easynetwork.lowlevel.api_async.backend.abc import TaskGroup

        handler = mocker.async_stub()
        handler.return_value = None
        task_group = mocker.NonCallableMagicMock(spec=TaskGroup) if external_group else None

        # Act
        with pytest.raises(asyncio.CancelledError):
            await tls_listener.serve(lambda stream: handler(stream), task_group)

        # Assert
        mock_wrapped_listener.serve.assert_awaited_once_with(mocker.ANY, task_group)
        mock_tls_wrap_transport.assert_awaited_once_with(
            mock_wrapped_client_transport,
            mock_ssl_context,
            server_side=True,
            handshake_timeout=handshake_timeout,
            shutdown_timeout=shutdown_timeout,
            standard_compatible=standard_compatible,
        )
        handler.assert_awaited_once_with(mock_tls_transport)

    @pytest.mark.parametrize(
        "exc",
        [
            *(OSError(errno, os.strerror(errno)) for errno in sorted(NOT_CONNECTED_SOCKET_ERRNOS)),
            ssl.CertificateError(),
            ssl.SSLEOFError(),
            ssl.SSLError(),
            Exception(),
            asyncio.CancelledError(),
            BaseException(),
        ],
        ids=repr,
    )
    async def test____serve____handshake_error(
        self,
        exc: BaseException,
        tls_listener: AsyncTLSListener,
        mock_wrapped_client_transport: MagicMock,
        mock_tls_wrap_transport: AsyncMock,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        caplog.set_level(logging.INFO)
        handler = mocker.async_stub()
        handler.return_value = None
        mock_tls_wrap_transport.side_effect = exc

        # Act
        with pytest.raises(BaseException) as exc_info:
            await tls_listener.serve(lambda stream: handler(stream))

        # Assert
        if type(exc) is BaseException:
            assert exc_info.value is exc
        else:
            assert isinstance(exc_info.value, asyncio.CancelledError)
        mock_tls_wrap_transport.assert_awaited_once()
        handler.assert_not_awaited()
        mock_wrapped_client_transport.aclose.assert_awaited_once_with()

        match exc:
            case asyncio.CancelledError():
                assert len(caplog.records) == 0
            case _:
                assert len(caplog.records) == 1
                assert caplog.records[0].levelno == logging.ERROR
                assert caplog.records[0].message == "Error in client task (during TLS handshake)"
                assert caplog.records[0].exc_info == (type(exc), exc, mocker.ANY)
