from __future__ import annotations

from easynetwork.exceptions import LimitOverrunError
from easynetwork.serializers.tools import GeneratorStreamReader

import pytest

from ...tools import next_return, send_return


class TestGeneratorStreamReader:
    def test____read_all____pop_buffer_without_copying(self) -> None:
        # Arrange
        initial_buffer = b"initial_buffer"
        reader = GeneratorStreamReader(initial_buffer)

        # Act
        data = reader.read_all()

        # Assert
        assert data is initial_buffer
        assert reader.read_all() == b""

    def test____read____yield_if_buffer_is_empty(self) -> None:
        # Arrange
        reader = GeneratorStreamReader()

        # Act
        consumer = reader.read(1024)
        next(consumer)
        data = send_return(consumer, b"data")

        # Assert
        assert data == b"data"

    def test____read____do_not_yield_if_buffer_is_not_empty(self) -> None:
        # Arrange
        reader = GeneratorStreamReader(b"data")

        # Act
        consumer = reader.read(1024)
        data = next_return(consumer)

        # Assert
        assert data == b"data"

    def test____read____no_data_copy____in_use_buffer(self) -> None:
        # Arrange
        value = b"data"
        reader = GeneratorStreamReader(value)

        # Act
        consumer = reader.read(1024)
        data = next_return(consumer)

        # Assert
        assert data is value

    def test____read____no_data_copy____sent_value(self) -> None:
        # Arrange
        value = b"data"
        reader = GeneratorStreamReader()

        # Act
        consumer = reader.read(1024)
        next(consumer)
        data = send_return(consumer, value)

        # Assert
        assert data is value

    @pytest.mark.parametrize("initial", [False, True], ids=lambda p: f"initial=={p}")
    def test____read____shrink_too_big_buffer(self, initial: bool) -> None:
        # Arrange
        value = b"data"
        reader = GeneratorStreamReader(value if initial else b"")

        # Act
        consumer = reader.read(2)
        if initial:
            data = next_return(consumer)
        else:
            next(consumer)
            data = send_return(consumer, value)

        # Assert
        assert data == b"da"
        assert reader.read_all() == b"ta"

    def test____read____null_nbytes(self) -> None:
        # Arrange
        reader = GeneratorStreamReader()

        # Act
        consumer = reader.read(0)
        data = next_return(consumer)

        # Assert
        assert data == b""

    def test____read____negative_nbytes(self) -> None:
        # Arrange
        reader = GeneratorStreamReader()

        # Act & Assert
        consumer = reader.read(-1)
        with pytest.raises(ValueError, match=r"^size must not be < 0$"):
            next_return(consumer)

    def test____read_exactly____yield_until_size_has_been_reached(self) -> None:
        # Arrange
        reader = GeneratorStreamReader()

        # Act
        consumer = reader.read_exactly(4)
        next(consumer)
        consumer.send(b"d")
        consumer.send(b"a")
        consumer.send(b"t")
        data = send_return(consumer, b"a")

        # Assert
        assert data == b"data"

    @pytest.mark.parametrize("initial", [False, True], ids=lambda p: f"initial=={p}")
    def test____read_exactly____size_already_fit(self, initial: bool) -> None:
        # Arrange
        value = b"data"
        reader = GeneratorStreamReader(value if initial else b"")

        # Act
        consumer = reader.read_exactly(4)
        if initial:
            data = next_return(consumer)
        else:
            next(consumer)
            data = send_return(consumer, value)

        # Assert
        assert data is value

    @pytest.mark.parametrize("initial", [False, True], ids=lambda p: f"initial=={p}")
    def test____read_exactly____shrink_too_big_buffer(self, initial: bool) -> None:
        # Arrange
        prefix = b"dat"
        reader = GeneratorStreamReader(prefix if initial else b"")

        # Act
        consumer = reader.read_exactly(4)
        next(consumer)
        if not initial:
            consumer.send(prefix)
        data = send_return(consumer, b"abc")

        # Assert
        assert data == b"data"
        assert reader.read_all() == b"bc"

    def test____read_exactly____null_nbytes(self) -> None:
        # Arrange
        reader = GeneratorStreamReader()

        # Act
        consumer = reader.read_exactly(0)
        data = next_return(consumer)

        # Assert
        assert data == b""

    def test____read_exactly____negative_nbytes(self) -> None:
        # Arrange
        reader = GeneratorStreamReader()

        # Act & Assert
        consumer = reader.read_exactly(-1)
        with pytest.raises(ValueError, match=r"^n must not be < 0$"):
            next_return(consumer)

    @pytest.mark.parametrize(
        "expected_remaining_data",
        [
            pytest.param(b"", id="without remaining data"),
            pytest.param(b"remaining", id="with remaining data"),
            pytest.param(b"remaining\r\nother", id="with remaining data including separator"),
        ],
    )
    @pytest.mark.parametrize("keep_end", [False, True], ids=lambda p: f"keep_end=={p}")
    def test____read_until____one_shot_chunk(self, expected_remaining_data: bytes, keep_end: bool) -> None:
        # Arrange
        reader = GeneratorStreamReader()
        data_to_test: bytes = b"data\r\n"

        # Act
        consumer = reader.read_until(b"\r\n", limit=1024, keep_end=keep_end)
        next(consumer)
        data = send_return(consumer, data_to_test + expected_remaining_data)

        # Assert
        if keep_end:
            assert data == b"data\r\n"
        else:
            assert data == b"data"
        assert reader.read_all() == expected_remaining_data

    @pytest.mark.parametrize(
        "expected_remaining_data",
        [
            pytest.param(b"", id="without remaining data"),
            pytest.param(b"remaining", id="with remaining data"),
            pytest.param(b"remaining\r\nother", id="with remaining data including separator"),
        ],
    )
    @pytest.mark.parametrize("keep_end", [False, True], ids=lambda p: f"keep_end=={p}")
    def test____read_until____several_chunks(self, expected_remaining_data: bytes, keep_end: bool) -> None:
        # Arrange
        reader = GeneratorStreamReader(b"d")

        # Act
        consumer = reader.read_until(b"\r\n", limit=1024, keep_end=keep_end)
        next(consumer)
        consumer.send(b"ata\r")
        data = send_return(consumer, b"\n" + expected_remaining_data)

        # Assert
        if keep_end:
            assert data == b"data\r\n"
        else:
            assert data == b"data"
        assert reader.read_all() == expected_remaining_data

    @pytest.mark.parametrize("separator_found", [False, True], ids=lambda p: f"separator_found=={p}")
    def test____read_until____reached_limit(self, separator_found: bytes) -> None:
        # Arrange
        reader = GeneratorStreamReader()
        data_to_test: bytes = b"data\r"
        if separator_found:
            data_to_test += b"\n"

        # Act
        consumer = reader.read_until(b"\r\n", limit=1)
        next(consumer)
        with pytest.raises(LimitOverrunError) as exc_info:
            consumer.send(data_to_test)

        # Assert
        if separator_found:
            assert str(exc_info.value) == "Separator is found, but chunk is longer than limit"
            assert bytes(exc_info.value.remaining_data) == b""
        else:
            assert str(exc_info.value) == "Separator is not found, and chunk exceed the limit"
            assert bytes(exc_info.value.remaining_data) == b"\r"

    def test____read_until____empty_separator(self) -> None:
        # Arrange
        reader = GeneratorStreamReader()

        # Act & Assert
        consumer = reader.read_until(b"", limit=1024)
        with pytest.raises(ValueError, match=r"^Empty separator$"):
            next_return(consumer)

    @pytest.mark.parametrize("limit", [0, -42], ids=lambda p: f"limit=={p}")
    def test____read_until____invalid_limit(self, limit: int) -> None:
        # Arrange
        reader = GeneratorStreamReader()

        # Act & Assert
        consumer = reader.read_until(b"\n", limit)
        with pytest.raises(ValueError, match=r"^limit must be a positive integer$"):
            next_return(consumer)
