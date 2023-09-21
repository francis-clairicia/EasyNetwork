from __future__ import annotations

import dataclasses
import uuid
from typing import Any, TypeGuard

from easynetwork.converter import AbstractPacketConverter
from easynetwork.exceptions import PacketConversionError


@dataclasses.dataclass
class Person:
    id: uuid.UUID
    name: str
    age: int
    friends: list[uuid.UUID] = dataclasses.field(default_factory=list)


class PersonToJSONConverter(AbstractPacketConverter[Person, dict[str, Any]]):
    def convert_to_dto_packet(self, person: Person, /) -> dict[str, Any]:
        return {
            "id": str(person.id),
            "name": person.name,
            "age": person.age,
            "friends": [str(friend_uuid) for friend_uuid in person.friends],
        }

    def create_from_dto_packet(self, packet: dict[str, Any], /) -> Person:
        match packet:
            case {
                "id": str(person_id),
                "name": str(name),
                "age": int(age),
                "friends": list(friends),
            } if self._is_valid_list_of_friends(friends):
                try:
                    person = Person(
                        id=uuid.UUID(person_id),
                        name=name,
                        age=age,
                        friends=[uuid.UUID(friend_id) for friend_id in friends],
                    )
                except ValueError:  # Invalid UUIDs
                    raise PacketConversionError("Invalid UUID fields") from None

            case _:
                raise PacketConversionError("Invalid packet format")

        return person

    @staticmethod
    def _is_valid_list_of_friends(friends_list: list[Any]) -> TypeGuard[list[str]]:
        return all(isinstance(friend_id, str) for friend_id in friends_list)
