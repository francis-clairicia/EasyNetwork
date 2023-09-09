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
"""EasyNetwork's packet converters module"""

from __future__ import annotations

__all__ = [
    "AbstractPacketConverter",
    "AbstractPacketConverterComposite",
    "PacketConverterComposite",
    "RequestResponseConverterBuilder",
]

from abc import ABCMeta, abstractmethod
from collections.abc import Callable
from typing import Any, Generic, final

from ._typevars import _DTOPacketT, _PacketT, _ReceivedPacketT, _SentPacketT


class AbstractPacketConverterComposite(Generic[_SentPacketT, _ReceivedPacketT, _DTOPacketT], metaclass=ABCMeta):
    """
    The base class for implementing a :term:`composite converter`.

    See Also:
        The :class:`AbstractPacketConverter` class.
    """

    __slots__ = ("__weakref__",)

    @abstractmethod
    def create_from_dto_packet(self, packet: _DTOPacketT, /) -> _ReceivedPacketT:
        """
        Constructs the business object from the :term:`DTO` `packet`.

        Parameters:
            packet: The :term:`data transfer object`.

        Raises:
            PacketConversionError: `packet` is invalid.

        Returns:
            the business object.
        """
        raise NotImplementedError

    @abstractmethod
    def convert_to_dto_packet(self, obj: _SentPacketT, /) -> _DTOPacketT:
        """
        Creates the :term:`DTO` packet from the business object `obj`.

        Parameters:
            obj: The business object.

        Returns:
            the :term:`data transfer object`.
        """
        raise NotImplementedError


class PacketConverterComposite(AbstractPacketConverterComposite[_SentPacketT, _ReceivedPacketT, _DTOPacketT]):
    """
    A :term:`composite converter` that merges two callables.
    """

    __slots__ = ("__create_from_dto", "__convert_to_dto")

    def __init__(
        self,
        *,
        convert_to_dto: Callable[[_SentPacketT], _DTOPacketT],
        create_from_dto: Callable[[_DTOPacketT], _ReceivedPacketT],
    ) -> None:
        """
        Parameters:
            convert_to_dto: Function called by :meth:`convert_to_dto_packet`.
            create_from_dto: Function called by :meth:`create_from_dto_packet`.
        """
        super().__init__()
        self.__create_from_dto: Callable[[_DTOPacketT], _ReceivedPacketT] = create_from_dto
        self.__convert_to_dto: Callable[[_SentPacketT], _DTOPacketT] = convert_to_dto

    @final
    def create_from_dto_packet(self, packet: _DTOPacketT, /) -> _ReceivedPacketT:
        """
        Calls `create_from_dto` with `packet`.

        Parameters:
            packet: The :term:`data transfer object`.

        Raises:
            PacketConversionError: `packet` is invalid.

        Returns:
            the business object.
        """
        create_from_dto_packet = self.__create_from_dto
        return create_from_dto_packet(packet)

    @final
    def convert_to_dto_packet(self, obj: _SentPacketT, /) -> _DTOPacketT:
        """
        Calls `convert_to_dto` with `obj`.

        Parameters:
            obj: The business object.

        Returns:
            the :term:`data transfer object`.
        """
        convert_to_dto_packet = self.__convert_to_dto
        return convert_to_dto_packet(obj)


class AbstractPacketConverter(AbstractPacketConverterComposite[_PacketT, _PacketT, _DTOPacketT], Generic[_PacketT, _DTOPacketT]):
    """
    The base class for implementing a :term:`converter`.

    See Also:
        The :class:`AbstractPacketConverterComposite` class.
    """

    __slots__ = ()

    @abstractmethod
    def create_from_dto_packet(self, packet: _DTOPacketT, /) -> _PacketT:
        raise NotImplementedError

    @abstractmethod
    def convert_to_dto_packet(self, obj: _PacketT, /) -> _DTOPacketT:
        raise NotImplementedError

    create_from_dto_packet.__doc__ = AbstractPacketConverterComposite.create_from_dto_packet.__doc__
    convert_to_dto_packet.__doc__ = AbstractPacketConverterComposite.convert_to_dto_packet.__doc__


@final
class RequestResponseConverterBuilder:
    """
    A :term:`composite converter` factory for request/response models.

    Example:

    The request converter:

    >>> class RequestConverter(AbstractPacketConverter):
    ...     def create_from_dto_packet(self, request_dto):
    ...         print(f"Creating request from DTO {request_dto!r}")
    ...         return "A request"
    ...     def convert_to_dto_packet(self, request):
    ...         print(f"Converting request {request!r} to DTO")
    ...         return "A DTO request"
    ...
    >>> request_converter = RequestConverter()

    The response converter:

    >>> class ResponseConverter(AbstractPacketConverter):
    ...     def create_from_dto_packet(self, response_dto):
    ...         print(f"Creating response from DTO {response_dto!r}")
    ...         return "A response"
    ...     def convert_to_dto_packet(self, response):
    ...         print(f"Converting response {response!r} to DTO")
    ...         return "A DTO response"
    ...
    >>> response_converter = ResponseConverter()

    The factory:

    >>> server_converter = RequestResponseConverterBuilder.build_for_server(request_converter, response_converter)
    >>> client_converter = RequestResponseConverterBuilder.build_for_client(request_converter, response_converter)

    A server receives requests and sends responses:

    >>> server_converter.create_from_dto_packet("request DTO")
    Creating request from DTO 'request DTO'
    'A request'
    >>> server_converter.convert_to_dto_packet("response")
    Converting response 'response' to DTO
    'A DTO response'

    A client sends requests and receives responses:

    >>> client_converter.convert_to_dto_packet("request")
    Converting request 'request' to DTO
    'A DTO request'
    >>> client_converter.create_from_dto_packet("response DTO")
    Creating response from DTO 'response DTO'
    'A response'
    """

    def __init_subclass__(cls) -> None:  # pragma: no cover
        raise TypeError("RequestResponseConverterBuilder cannot be subclassed")

    @staticmethod
    def build_for_client(
        request_converter: AbstractPacketConverterComposite[_SentPacketT, Any, _DTOPacketT],
        response_converter: AbstractPacketConverterComposite[Any, _ReceivedPacketT, _DTOPacketT],
    ) -> AbstractPacketConverterComposite[_SentPacketT, _ReceivedPacketT, _DTOPacketT]:
        """
        Creates a :term:`composite converter` that merges these two converters for client purposes.

        See :class:`RequestResponseConverterBuilder`'s docstring for examples.

        Parameters:
            request_converter: The request :term:`converter`.
            response_converter: The response :term:`converter`.

        Returns:
            a :term:`composite converter`.
        """
        return PacketConverterComposite(
            create_from_dto=response_converter.create_from_dto_packet,
            convert_to_dto=request_converter.convert_to_dto_packet,
        )

    @staticmethod
    def build_for_server(
        request_converter: AbstractPacketConverterComposite[Any, _ReceivedPacketT, _DTOPacketT],
        response_converter: AbstractPacketConverterComposite[_SentPacketT, Any, _DTOPacketT],
    ) -> AbstractPacketConverterComposite[_SentPacketT, _ReceivedPacketT, _DTOPacketT]:
        """
        Creates a :term:`composite converter` that merges these two converters for server purposes.

        See :class:`RequestResponseConverterBuilder`'s docstring for examples.

        Parameters:
            request_converter: The request :term:`converter`.
            response_converter: The response :term:`converter`.

        Returns:
            a :term:`composite converter`.
        """
        return PacketConverterComposite(
            create_from_dto=request_converter.create_from_dto_packet,
            convert_to_dto=response_converter.convert_to_dto_packet,
        )
