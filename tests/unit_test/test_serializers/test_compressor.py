from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Literal

from easynetwork.exceptions import DeserializeError, IncrementalDeserializeError
from easynetwork.serializers.wrapper.compressor import (
    AbstractCompressorSerializer,
    BZ2CompressorSerializer,
    ZlibCompressorSerializer,
)

import pytest

from ...tools import send_return, write_in_buffer

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from _typeshed import ReadableBuffer
    from pytest_mock import MockerFixture


class _CompressorSerializerForTest(AbstractCompressorSerializer[Any, Any]):
    def new_compressor_stream(self) -> Any:
        raise NotImplementedError

    def new_decompressor_stream(self) -> Any:
        raise NotImplementedError


class TestAbstractCompressorSerializer:
    @pytest.fixture
    @staticmethod
    def mock_serializer_new_compressor_stream(mocker: MockerFixture) -> MagicMock:
        return mocker.patch.object(_CompressorSerializerForTest, "new_compressor_stream")

    @pytest.fixture
    @staticmethod
    def mock_compressor_stream(mock_serializer_new_compressor_stream: MagicMock) -> MagicMock:
        return mock_serializer_new_compressor_stream.return_value

    @pytest.fixture
    @staticmethod
    def mock_serializer_new_decompressor_stream(mocker: MockerFixture) -> MagicMock:
        return mocker.patch.object(_CompressorSerializerForTest, "new_decompressor_stream")

    @pytest.fixture
    @staticmethod
    def mock_decompressor_stream_eof(mocker: MockerFixture) -> MagicMock:
        mock = mocker.PropertyMock()
        del mock.__set__
        del mock.__delete__
        return mock

    @pytest.fixture
    @staticmethod
    def mock_decompressor_stream_unused_data(mocker: MockerFixture) -> MagicMock:
        mock = mocker.PropertyMock()
        del mock.__set__
        del mock.__delete__
        return mock

    @pytest.fixture
    @staticmethod
    def mock_decompressor_stream(
        mock_serializer_new_decompressor_stream: MagicMock,
        mock_decompressor_stream_eof: MagicMock,
        mock_decompressor_stream_unused_data: MagicMock,
    ) -> Iterator[MagicMock]:
        mock: MagicMock = mock_serializer_new_decompressor_stream.return_value
        mock.unused_data = b""
        type(mock).eof = mock_decompressor_stream_eof
        type(mock).unused_data = mock_decompressor_stream_unused_data
        yield mock
        del type(mock).eof
        del type(mock).unused_data

    @pytest.fixture(params=["data", "buffer"])
    @staticmethod
    def incremental_deserialize_mode(request: pytest.FixtureRequest) -> str:
        assert request.param in ("data", "buffer")
        return request.param

    def test____properties____right_values(self, mock_serializer: MagicMock, debug_mode: bool) -> None:
        # Arrange

        # Act
        serializer = _CompressorSerializerForTest(mock_serializer, expected_decompress_error=(), debug=debug_mode)

        # Assert
        assert serializer.debug is debug_mode

    def test____dunder_init____invalid_serializer(self, mocker: MockerFixture) -> None:
        # Arrange
        mock_not_serializer = mocker.NonCallableMagicMock(spec=object)

        # Act
        with pytest.raises(TypeError, match=r"^Expected a serializer instance, got .+$"):
            _CompressorSerializerForTest(mock_not_serializer, ())

    def test____serialize____compress_data(
        self,
        mock_serializer: MagicMock,
        mock_serializer_new_compressor_stream: MagicMock,
        mock_compressor_stream: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _CompressorSerializerForTest(mock_serializer, ())
        mock_serializer.serialize.return_value = mocker.sentinel.data
        mock_compressor_stream.compress.return_value = b"compressed data + "
        mock_compressor_stream.flush.return_value = b"flush"

        # Act
        data = serializer.serialize(mocker.sentinel.packet)

        # Assert
        mock_serializer_new_compressor_stream.assert_called_once_with()
        mock_serializer.serialize.assert_called_once_with(mocker.sentinel.packet)
        mock_compressor_stream.compress.assert_called_once_with(mocker.sentinel.data)
        mock_compressor_stream.flush.assert_called_once_with()
        assert data == b"compressed data + flush"

    def test____incremental_serialize____compress_data(
        self,
        mock_serializer: MagicMock,
        mock_serializer_new_compressor_stream: MagicMock,
        mock_compressor_stream: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _CompressorSerializerForTest(mock_serializer, ())
        mock_serializer.serialize.return_value = mocker.sentinel.data
        mock_compressor_stream.compress.return_value = b"compressed data"
        mock_compressor_stream.flush.return_value = b"flush"

        # Act
        chunks = list(serializer.incremental_serialize(mocker.sentinel.packet))

        # Assert
        mock_serializer_new_compressor_stream.assert_called_once_with()
        mock_serializer.serialize.assert_called_once_with(mocker.sentinel.packet)
        mock_compressor_stream.compress.assert_called_once_with(mocker.sentinel.data)
        mock_compressor_stream.flush.assert_called_once_with()
        assert chunks == [b"compressed data", b"flush"]

    def test____deserialize____decompress_data(
        self,
        mock_serializer: MagicMock,
        mock_serializer_new_decompressor_stream: MagicMock,
        mock_decompressor_stream: MagicMock,
        mock_decompressor_stream_eof: MagicMock,
        mock_decompressor_stream_unused_data: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _CompressorSerializerForTest(mock_serializer, ())
        mock_decompressor_stream_eof.return_value = True
        mock_decompressor_stream_unused_data.return_value = b""
        mock_decompressor_stream.decompress.return_value = mocker.sentinel.decompressed_data
        mock_serializer.deserialize.return_value = mocker.sentinel.packet

        # Act
        packet = serializer.deserialize(mocker.sentinel.data)

        # Assert
        mock_serializer_new_decompressor_stream.assert_called_once_with()
        mock_decompressor_stream.decompress.assert_called_once_with(mocker.sentinel.data)
        mock_decompressor_stream_eof.assert_called_once()
        mock_decompressor_stream_unused_data.assert_called_once()
        mock_serializer.deserialize.assert_called_once_with(mocker.sentinel.decompressed_data)
        assert packet is mocker.sentinel.packet

    @pytest.mark.parametrize("give_as_tuple", [False, True], ids=lambda boolean: f"give_as_tuple=={boolean}")
    def test____deserialize____translates_given_exceptions(
        self,
        give_as_tuple: bool,
        mock_serializer: MagicMock,
        mock_serializer_new_decompressor_stream: MagicMock,
        mock_decompressor_stream: MagicMock,
        mock_decompressor_stream_eof: MagicMock,
        mock_decompressor_stream_unused_data: MagicMock,
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        class MyStreamAPIBaseException(Exception):
            pass

        class MyStreamAPIValueError(MyStreamAPIBaseException, ValueError):
            pass

        if give_as_tuple:
            serializer = _CompressorSerializerForTest(
                mock_serializer,
                expected_decompress_error=(MyStreamAPIBaseException,),
                debug=debug_mode,
            )
        else:
            serializer = _CompressorSerializerForTest(
                mock_serializer,
                expected_decompress_error=MyStreamAPIBaseException,
                debug=debug_mode,
            )
        mock_decompressor_stream.decompress.side_effect = MyStreamAPIValueError()

        # Act
        with pytest.raises(DeserializeError) as exc_info:
            _ = serializer.deserialize(mocker.sentinel.data)
        exception = exc_info.value

        # Assert
        mock_serializer_new_decompressor_stream.assert_called_once_with()
        mock_decompressor_stream.decompress.assert_called_once_with(mocker.sentinel.data)
        mock_decompressor_stream_eof.assert_not_called()
        mock_decompressor_stream_unused_data.assert_not_called()
        mock_serializer.deserialize.assert_not_called()
        assert exception.__cause__ is mock_decompressor_stream.decompress.side_effect
        if debug_mode:
            assert exception.error_info == {"data": mocker.sentinel.data}
        else:
            assert exception.error_info is None

    def test____deserialize____missing_data(
        self,
        mock_serializer: MagicMock,
        mock_serializer_new_decompressor_stream: MagicMock,
        mock_decompressor_stream: MagicMock,
        mock_decompressor_stream_eof: MagicMock,
        mock_decompressor_stream_unused_data: MagicMock,
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _CompressorSerializerForTest(mock_serializer, (), debug=debug_mode)
        mock_decompressor_stream.decompress.return_value = mocker.sentinel.decompressed_data
        mock_decompressor_stream_eof.return_value = False

        # Act
        with pytest.raises(
            DeserializeError, match=r"^Compressed data ended before the end-of-stream marker was reached$"
        ) as exc_info:
            _ = serializer.deserialize(mocker.sentinel.data)
        exception = exc_info.value

        # Assert
        mock_serializer_new_decompressor_stream.assert_called_once_with()
        mock_decompressor_stream.decompress.assert_called_once_with(mocker.sentinel.data)
        mock_decompressor_stream_eof.assert_called_once()
        mock_decompressor_stream_unused_data.assert_not_called()
        mock_serializer.deserialize.assert_not_called()
        if debug_mode:
            assert exception.error_info == {"already_decompressed_data": mocker.sentinel.decompressed_data}
        else:
            assert exception.error_info is None

    def test____deserialize____extra_data(
        self,
        mock_serializer: MagicMock,
        mock_serializer_new_decompressor_stream: MagicMock,
        mock_decompressor_stream: MagicMock,
        mock_decompressor_stream_eof: MagicMock,
        mock_decompressor_stream_unused_data: MagicMock,
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _CompressorSerializerForTest(mock_serializer, (), debug=debug_mode)
        mock_decompressor_stream.decompress.return_value = mocker.sentinel.decompressed_data
        mock_decompressor_stream_eof.return_value = True
        mock_decompressor_stream_unused_data.return_value = b"some extra data"

        # Act
        with pytest.raises(DeserializeError, match=r"^Trailing data error$") as exc_info:
            _ = serializer.deserialize(mocker.sentinel.data)
        exception = exc_info.value

        # Assert
        mock_serializer_new_decompressor_stream.assert_called_once_with()
        mock_decompressor_stream.decompress.assert_called_once_with(mocker.sentinel.data)
        mock_decompressor_stream_eof.assert_called_once()
        if debug_mode:
            assert mock_decompressor_stream_unused_data.call_count == 2
        else:
            assert mock_decompressor_stream_unused_data.call_count == 1
        mock_serializer.deserialize.assert_not_called()
        if debug_mode:
            assert exception.error_info == {"decompressed_data": mocker.sentinel.decompressed_data, "extra": b"some extra data"}
        else:
            assert exception.error_info is None

    def test____incremental_deserialize____decompress_chunks(
        self,
        incremental_deserialize_mode: Literal["data", "buffer"],
        mock_serializer: MagicMock,
        mock_serializer_new_decompressor_stream: MagicMock,
        mock_decompressor_stream: MagicMock,
        mock_decompressor_stream_eof: MagicMock,
        mock_decompressor_stream_unused_data: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        given_chunks: list[bytes] = []

        def decompress_side_effect(b: ReadableBuffer) -> bytes:
            given_chunks.append(bytes(b))
            return b"decompressed " + b

        serializer = _CompressorSerializerForTest(mock_serializer, ())
        mock_decompressor_stream_eof.side_effect = [False, False, True]
        mock_decompressor_stream_unused_data.return_value = b"some extra data"
        mock_decompressor_stream.decompress.side_effect = decompress_side_effect
        mock_serializer.deserialize.return_value = mocker.sentinel.packet

        # Act
        remaining_data: ReadableBuffer
        match incremental_deserialize_mode:
            case "data":
                data_consumer = serializer.incremental_deserialize()
                next(data_consumer)
                data_consumer.send(b"chunk 1")
                packet, remaining_data = send_return(data_consumer, b"chunk 2")
            case "buffer":
                buffer = serializer.create_deserializer_buffer(1024)
                buffered_consumer = serializer.buffered_incremental_deserialize(buffer)
                next(buffered_consumer)
                buffered_consumer.send(write_in_buffer(buffer, b"chunk 1"))
                packet, remaining_data = send_return(buffered_consumer, write_in_buffer(buffer, b"chunk 2"))
            case _:
                pytest.fail("Invalid fixture argument")

        # Assert
        mock_serializer_new_decompressor_stream.assert_called_once_with()
        assert mock_decompressor_stream.decompress.call_count == 2
        assert given_chunks == [b"chunk 1", b"chunk 2"]
        assert len(mock_decompressor_stream_eof.call_args_list) == 3
        mock_decompressor_stream_unused_data.assert_called_once()
        mock_serializer.deserialize.assert_called_once_with(b"decompressed chunk 1decompressed chunk 2")
        assert packet is mocker.sentinel.packet
        assert remaining_data == b"some extra data"

    @pytest.mark.parametrize("give_as_tuple", [False, True], ids=lambda boolean: f"give_as_tuple=={boolean}")
    def test____incremental_deserialize____translate_given_exceptions(
        self,
        give_as_tuple: bool,
        incremental_deserialize_mode: Literal["data", "buffer"],
        mock_serializer: MagicMock,
        mock_serializer_new_decompressor_stream: MagicMock,
        mock_decompressor_stream: MagicMock,
        mock_decompressor_stream_eof: MagicMock,
        mock_decompressor_stream_unused_data: MagicMock,
        debug_mode: bool,
    ) -> None:
        # Arrange
        from collections import deque

        class MyStreamAPIBaseException(Exception):
            pass

        class MyStreamAPIValueError(MyStreamAPIBaseException, ValueError):
            pass

        if give_as_tuple:
            serializer = _CompressorSerializerForTest(
                mock_serializer,
                expected_decompress_error=(MyStreamAPIBaseException,),
                debug=debug_mode,
            )
        else:
            serializer = _CompressorSerializerForTest(
                mock_serializer,
                expected_decompress_error=MyStreamAPIBaseException,
                debug=debug_mode,
            )
        mock_decompressor_stream_eof.side_effect = [False]
        mock_decompressor_stream.decompress.side_effect = MyStreamAPIValueError()

        # Act
        match incremental_deserialize_mode:
            case "data":
                data_consumer = serializer.incremental_deserialize()
                next(data_consumer)
                with pytest.raises(IncrementalDeserializeError) as exc_info:
                    data_consumer.send(b"chunk")
            case "buffer":
                buffer = serializer.create_deserializer_buffer(1024)
                buffered_consumer = serializer.buffered_incremental_deserialize(buffer)
                next(buffered_consumer)
                with pytest.raises(IncrementalDeserializeError) as exc_info:
                    buffered_consumer.send(write_in_buffer(buffer, b"chunk"))
            case _:
                pytest.fail("Invalid fixture argument")

        exception = exc_info.value

        # Assert
        mock_serializer_new_decompressor_stream.assert_called_once_with()
        mock_decompressor_stream.decompress.assert_called_once_with(b"chunk")
        mock_decompressor_stream_eof.assert_called_once()
        mock_decompressor_stream_unused_data.assert_not_called()
        mock_serializer.deserialize.assert_not_called()
        assert exception.__cause__ is mock_decompressor_stream.decompress.side_effect
        assert bytes(exception.remaining_data) == b""
        if debug_mode:
            assert exception.error_info == {
                "already_decompressed_chunks": deque([]),
                "invalid_chunk": b"chunk",
            }
        else:
            assert exception.error_info is None

    def test____incremental_deserialize____translate_deserialize_errors(
        self,
        incremental_deserialize_mode: Literal["data", "buffer"],
        mock_serializer: MagicMock,
        mock_serializer_new_decompressor_stream: MagicMock,
        mock_decompressor_stream: MagicMock,
        mock_decompressor_stream_eof: MagicMock,
        mock_decompressor_stream_unused_data: MagicMock,
        debug_mode: bool,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer = _CompressorSerializerForTest(mock_serializer, (), debug=debug_mode)
        mock_decompressor_stream_eof.side_effect = [False, True]
        mock_decompressor_stream_unused_data.return_value = mocker.sentinel.unused_data
        mock_decompressor_stream.decompress.side_effect = [b"decompressed chunk"]
        mock_serializer.deserialize.side_effect = DeserializeError("Bad news", error_info=mocker.sentinel.error_info)

        # Act
        match incremental_deserialize_mode:
            case "data":
                data_consumer = serializer.incremental_deserialize()
                next(data_consumer)
                with pytest.raises(IncrementalDeserializeError) as exc_info:
                    data_consumer.send(b"chunk")
            case "buffer":
                buffer = serializer.create_deserializer_buffer(1024)
                buffered_consumer = serializer.buffered_incremental_deserialize(buffer)
                next(buffered_consumer)
                with pytest.raises(IncrementalDeserializeError) as exc_info:
                    buffered_consumer.send(write_in_buffer(buffer, b"chunk"))
            case _:
                pytest.fail("Invalid fixture argument")
        exception = exc_info.value

        # Assert
        mock_serializer_new_decompressor_stream.assert_called_once_with()
        mock_decompressor_stream.decompress.assert_called_once_with(b"chunk")
        assert len(mock_decompressor_stream_eof.call_args_list) == 2
        mock_decompressor_stream_unused_data.assert_called_once()
        mock_serializer.deserialize.assert_called_once_with(b"decompressed chunk")
        assert exception.__cause__ is mock_serializer.deserialize.side_effect
        assert exception.remaining_data is mocker.sentinel.unused_data
        assert exception.error_info is mocker.sentinel.error_info


class BaseTestCompressorSerializerImplementation:
    @pytest.mark.parametrize(
        "method",
        [
            "serialize",
            "incremental_serialize",
            "deserialize",
            "incremental_deserialize",
            "create_deserializer_buffer",
            "buffered_incremental_deserialize",
        ],
    )
    def test____base_class____implements_default_methods(
        self,
        serializer_cls: type[AbstractCompressorSerializer[Any, Any]],
        method: str,
    ) -> None:
        # Arrange

        # Act & Assert
        assert getattr(serializer_cls, method) is getattr(AbstractCompressorSerializer, method)


class TestBZ2CompressorSerializer(BaseTestCompressorSerializerImplementation):
    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_cls() -> type[BZ2CompressorSerializer[Any, Any]]:
        return BZ2CompressorSerializer

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_bz2_compressor_cls(mocker: MockerFixture) -> MagicMock:
        return mocker.patch("bz2.BZ2Compressor")

    @pytest.fixture(autouse=True)
    @staticmethod
    def mock_bz2_decompressor_cls(mocker: MockerFixture) -> MagicMock:
        return mocker.patch("bz2.BZ2Decompressor")

    def test____properties____right_values(self, mock_serializer: MagicMock, debug_mode: bool) -> None:
        # Arrange

        # Act
        serializer: BZ2CompressorSerializer[Any, Any] = BZ2CompressorSerializer(mock_serializer, debug=debug_mode)

        # Assert
        assert serializer.debug is debug_mode

    @pytest.mark.parametrize(
        "with_compress_level",
        [
            pytest.param(False, id="without specifying level"),
            pytest.param(True, id="specifying level"),
        ],
    )
    def test____new_compressor_stream____returns_bz2_compressor(
        self,
        with_compress_level: bool,
        mock_bz2_compressor_cls: MagicMock,
        mock_serializer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: BZ2CompressorSerializer[Any, Any]
        if with_compress_level:
            serializer = BZ2CompressorSerializer(mock_serializer, compress_level=mocker.sentinel.compresslevel)
        else:
            serializer = BZ2CompressorSerializer(mock_serializer)
        mock_bz2_compressor_cls.return_value = mocker.sentinel.stream

        # Act
        stream = serializer.new_compressor_stream()

        # Assert
        if with_compress_level:
            mock_bz2_compressor_cls.assert_called_once_with(mocker.sentinel.compresslevel)
        else:
            mock_bz2_compressor_cls.assert_called_once_with(mocker.ANY)
        assert stream is mocker.sentinel.stream

    def test____new_decompressor_stream____returns_bz2_decompressor(
        self,
        mock_bz2_decompressor_cls: MagicMock,
        mock_serializer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: BZ2CompressorSerializer[Any, Any] = BZ2CompressorSerializer(mock_serializer)
        mock_bz2_decompressor_cls.return_value = mocker.sentinel.stream

        # Act
        stream = serializer.new_decompressor_stream()

        # Assert
        mock_bz2_decompressor_cls.assert_called_once_with()
        assert stream is mocker.sentinel.stream


class TestZlibCompressorSerializer(BaseTestCompressorSerializerImplementation):
    @pytest.fixture(scope="class")
    @staticmethod
    def serializer_cls() -> type[ZlibCompressorSerializer[Any, Any]]:
        return ZlibCompressorSerializer

    @pytest.fixture
    @staticmethod
    def mock_zlib_compressor_cls(mocker: MockerFixture) -> MagicMock:
        return mocker.patch("zlib.compressobj")

    @pytest.fixture
    @staticmethod
    def mock_zlib_decompressor_cls(mocker: MockerFixture) -> MagicMock:
        return mocker.patch("zlib.decompressobj")

    def test____properties____right_values(self, mock_serializer: MagicMock, debug_mode: bool) -> None:
        # Arrange

        # Act
        serializer: ZlibCompressorSerializer[Any, Any] = ZlibCompressorSerializer(mock_serializer, debug=debug_mode)

        # Assert
        assert serializer.debug is debug_mode

    @pytest.mark.parametrize(
        "with_compress_level",
        [
            pytest.param(False, id="without specifying level"),
            pytest.param(True, id="specifying level"),
        ],
    )
    def test____new_compressor_stream____returns_bz2_compressor(
        self,
        with_compress_level: bool,
        mock_zlib_compressor_cls: MagicMock,
        mock_serializer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: ZlibCompressorSerializer[Any, Any]
        if with_compress_level:
            serializer = ZlibCompressorSerializer(mock_serializer, compress_level=mocker.sentinel.compresslevel)
        else:
            serializer = ZlibCompressorSerializer(mock_serializer)
        mock_zlib_compressor_cls.return_value = mocker.sentinel.stream

        # Act
        stream = serializer.new_compressor_stream()

        # Assert
        if with_compress_level:
            mock_zlib_compressor_cls.assert_called_once_with(mocker.sentinel.compresslevel)
        else:
            mock_zlib_compressor_cls.assert_called_once_with(mocker.ANY)
        assert stream is mocker.sentinel.stream

    def test____new_decompressor_stream____returns_bz2_decompressor(
        self,
        mock_zlib_decompressor_cls: MagicMock,
        mock_serializer: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        # Arrange
        serializer: ZlibCompressorSerializer[Any, Any] = ZlibCompressorSerializer(mock_serializer)
        mock_zlib_decompressor_cls.return_value = mocker.sentinel.stream

        # Act
        stream = serializer.new_decompressor_stream()

        # Assert
        mock_zlib_decompressor_cls.assert_called_once_with()
        assert stream is mocker.sentinel.stream
