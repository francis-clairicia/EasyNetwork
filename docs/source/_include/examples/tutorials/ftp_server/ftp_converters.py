from __future__ import annotations

from easynetwork.converter import AbstractPacketConverter
from easynetwork.exceptions import PacketConversionError

from ftp_command import FTPCommand
from ftp_reply import FTPReply
from ftp_request import FTPRequest


class FTPRequestConverter(AbstractPacketConverter[FTPRequest, str]):
    """Converter to switch between FTPRequest objects and strings."""

    def convert_to_dto_packet(self, obj: FTPRequest) -> str:
        """Creates the string representation of the FTPRequest object

        Not implemented.
        """

        raise NotImplementedError("Not needed in server side")

    def create_from_dto_packet(self, packet: str) -> FTPRequest:
        """Builds an FTPRequest object from a raw string

        >>> c = FTPRequestConverter()
        >>> c.create_from_dto_packet("NOOP")
        FTPRequest(command=<FTPCommand.NOOP: 'NOOP'>, args=())
        >>> c.create_from_dto_packet("qUiT")
        FTPRequest(command=<FTPCommand.QUIT: 'QUIT'>, args=())
        >>> c.create_from_dto_packet("STOR /path/file.txt")
        FTPRequest(command=<FTPCommand.STOR: 'STOR'>, args=('/path/file.txt',))
        >>> c.create_from_dto_packet("invalid command")
        Traceback (most recent call last):
        ...
        easynetwork.exceptions.PacketConversionError: Command unrecognized: 'INVALID'

        Parameters:
            packet: The string representation of the request

        Returns:
            the FTP request
        """
        command, *args = packet.split(" ")
        command = command.upper()
        try:
            command = FTPCommand(command)
        except ValueError as exc:
            raise PacketConversionError(f"Command unrecognized: {command!r}") from exc
        return FTPRequest(command, tuple(args))


class FTPReplyConverter(AbstractPacketConverter[FTPReply, str]):
    """Converter to switch between FTPReply objects and strings."""

    def convert_to_dto_packet(self, obj: FTPReply) -> str:
        """Creates the string representation of the FTPReply object

        >>> c = FTPReplyConverter()
        >>> c.convert_to_dto_packet(FTPReply(200, "Command okay."))
        '200 Command okay.'
        >>> c.convert_to_dto_packet(FTPReply(10, "Does not exist but why not."))
        '010 Does not exist but why not.'

        Parameters:
            obj: The FTPReply object

        Returns:
            the string representation of the reply
        """

        code: int = obj.code
        message: str = obj.message

        assert 0 <= code < 1000, f"Invalid reply code {code:d}"

        # Multi-line replies exist, but we won't deal with them in this tutorial.
        assert "\n" not in message, "message contains newline character"
        separator = " "

        return f"{code:03d}{separator}{message}"

    def create_from_dto_packet(self, packet: str) -> FTPReply:
        """Builds an FTPReply object from a raw string

        Not implemented.
        """
        raise NotImplementedError("Not needed in server side")
