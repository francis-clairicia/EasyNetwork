from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from easynetwork.exceptions import TypedAttributeLookupError
from easynetwork.lowlevel.typed_attr import TypedAttributeProvider, TypedAttributeSet, typed_attribute

import pytest

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


class TestTypedAttributeSet:
    def test____typed_attr____missing_annotations(self) -> None:
        # Arrange

        # Act & Assert
        with pytest.raises(TypeError, match=r"^Attribute 'socket' is missing its type annotation$"):

            class SocketAttribute(TypedAttributeSet):
                socket = typed_attribute()

            del SocketAttribute


class TestTypedAttributeProvider:
    def test____extra____call_defined_extra_callback(self, mocker: MockerFixture) -> None:
        # Arrange
        extra_stub: MagicMock = mocker.stub()
        extra_stub.return_value = mocker.sentinel.extra_value

        class Attribute(TypedAttributeSet):
            extra: Any = typed_attribute()

        class Provider(TypedAttributeProvider):
            @property
            def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
                return {
                    **super().extra_attributes,
                    Attribute.extra: extra_stub,
                }

        provider = Provider()

        # Act
        extra_value = provider.extra(Attribute.extra)

        # Assert
        extra_stub.assert_called_once_with()
        assert extra_value is mocker.sentinel.extra_value

    def test____extra____missing_extra____no_default(self, mocker: MockerFixture) -> None:
        # Arrange
        class Attribute(TypedAttributeSet):
            extra: Any = typed_attribute()

        class Provider(TypedAttributeProvider):
            @property
            def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
                return {}

        provider = Provider()

        # Act & Assert
        with pytest.raises(TypedAttributeLookupError, match=r"^Attribute not found$"):
            _ = provider.extra(Attribute.extra)

    def test____extra____missing_extra____default(self, mocker: MockerFixture) -> None:
        # Arrange
        class Attribute(TypedAttributeSet):
            extra: Any = typed_attribute()

        class Provider(TypedAttributeProvider):
            @property
            def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
                return {}

        provider = Provider()

        # Act
        extra_value = provider.extra(Attribute.extra, mocker.sentinel.default_value)

        # Assert
        assert extra_value is mocker.sentinel.default_value

    def test____extra____not_available____no_default(self, mocker: MockerFixture) -> None:
        # Arrange
        extra_stub: MagicMock = mocker.stub()
        extra_stub.side_effect = TypedAttributeLookupError("extra_stub has no value")

        class Attribute(TypedAttributeSet):
            extra: Any = typed_attribute()

        class Provider(TypedAttributeProvider):
            @property
            def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
                return {Attribute.extra: extra_stub}

        provider = Provider()

        # Act & Assert
        with pytest.raises(TypedAttributeLookupError, match=r"^extra_stub has no value$"):
            _ = provider.extra(Attribute.extra)

        extra_stub.assert_called_once_with()

    def test____extra____not_available____default(self, mocker: MockerFixture) -> None:
        # Arrange
        extra_stub: MagicMock = mocker.stub()
        extra_stub.side_effect = TypedAttributeLookupError("extra_stub has no value")

        class Attribute(TypedAttributeSet):
            extra: Any = typed_attribute()

        class Provider(TypedAttributeProvider):
            @property
            def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
                return {Attribute.extra: extra_stub}

        provider = Provider()

        # Act
        extra_value = provider.extra(Attribute.extra, mocker.sentinel.default_value)

        # Assert
        assert extra_value is mocker.sentinel.default_value
        extra_stub.assert_called_once_with()
