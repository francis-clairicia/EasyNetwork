from __future__ import annotations

import uuid

from easynetwork.clients import TCPNetworkClient
from easynetwork.exceptions import DeserializeError, PacketConversionError, StreamProtocolParseError
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer

from .example1 import Person, PersonToJSONConverter


class PersonProtocol(StreamProtocol[Person, Person]):
    def __init__(self) -> None:
        serializer = JSONSerializer()
        converter = PersonToJSONConverter()

        super().__init__(serializer, converter=converter)


def main() -> None:
    protocol = PersonProtocol()

    with TCPNetworkClient(("remote_address", 12345), protocol) as endpoint:
        john_doe = Person(
            id=uuid.uuid4(),
            name="John Doe",
            age=36,
            friends=[uuid.uuid4() for _ in range(5)],
        )

        # Person object directly sent
        endpoint.send_packet(john_doe)

        try:
            # The received object should be a Person instance.
            received_person = endpoint.recv_packet()
        except StreamProtocolParseError as exc:
            match exc.error:
                case DeserializeError():
                    print("It is not even a JSON object.")
                case PacketConversionError():
                    print("It is not a valid Person in JSON object.")
        else:
            assert isinstance(received_person, Person)
            print(f"Received person: {received_person!r}")
