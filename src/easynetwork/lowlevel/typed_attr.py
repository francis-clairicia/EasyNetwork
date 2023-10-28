# Copyright 2021-2023, Francis Clairicia-Rose-Claire-Josephine
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
"""Backport of AnyIO's typed attributes."""

from __future__ import annotations

__all__ = ["TypedAttributeProvider", "TypedAttributeSet"]

from collections.abc import Callable, Mapping
from typing import Any, TypeVar, final, overload

from ..exceptions import TypedAttributeLookupError

T_Attr = TypeVar("T_Attr")
T_Default = TypeVar("T_Default")
undefined = object()


def typed_attribute() -> Any:
    """Return a unique object, used to mark typed attributes."""
    return object()


class TypedAttributeSet:
    """
    Superclass for typed attribute collections.

    Checks that every public attribute of every subclass has a type annotation.
    """

    __slots__ = ()

    def __init_subclass__(cls) -> None:
        annotations: dict[str, Any] = getattr(cls, "__annotations__", {})
        for attrname in vars(cls):
            if not attrname.startswith("_") and attrname not in annotations:
                raise TypeError(f"Attribute {attrname!r} is missing its type annotation")

        super().__init_subclass__()


class TypedAttributeProvider:
    """Base class for classes that wish to provide typed extra attributes."""

    __slots__ = ()

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        """
        A mapping of the extra attributes to callables that return the corresponding
        values.

        If the provider wraps another provider, the attributes from that wrapper should
        also be included in the returned mapping (but the wrapper may override the
        callables from the wrapped instance).

        The callables should raise :exc:`TypedAttributeLookupError` if it is not possible to get the value.
        """
        return {}

    @overload
    def extra(self, attribute: T_Attr) -> T_Attr:
        ...

    @overload
    def extra(self, attribute: T_Attr, default: T_Default) -> T_Attr | T_Default:
        ...

    @final
    def extra(self, attribute: Any, default: object = undefined) -> object:
        """
        Return the value of the given typed extra attribute.

        Parameters:
            attribute: the attribute (member of a :class:`TypedAttributeSet`) to look for
            default: the value that should be returned if no value is found for the attribute

        Raises:
            TypedAttributeLookupError: if the search failed and no default value was given
        """
        try:
            try:
                extra = self.extra_attributes[attribute]
            except KeyError:
                raise TypedAttributeLookupError("Attribute not found") from None
            return extra()
        except TypedAttributeLookupError:
            if default is undefined:
                raise
            else:
                return default
