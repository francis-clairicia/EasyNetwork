# Code taken from anyio (https://github.com/agronholm/anyio/tree/4.2.0)
#
# Copyright (c) 2018 Alex Grönholm
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
# the Software, and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
# FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
# COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
# IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

"""Backport of AnyIO's typed attributes."""

from __future__ import annotations

__all__ = ["TypedAttributeProvider", "TypedAttributeSet"]

from collections.abc import Callable, Mapping
from typing import Any, TypeVar, final, overload

from ..exceptions import TypedAttributeLookupError

_T_Attr = TypeVar("_T_Attr")
_T_Default = TypeVar("_T_Default")
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

        The callables should raise :exc:`.TypedAttributeLookupError` if it is not possible to get the value.
        """
        return {}

    @overload
    def extra(self, attribute: _T_Attr) -> _T_Attr: ...

    @overload
    def extra(self, attribute: _T_Attr, default: _T_Default) -> _T_Attr | _T_Default: ...

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
