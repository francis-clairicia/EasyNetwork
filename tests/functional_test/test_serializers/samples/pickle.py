# -*- coding: Utf-8 -*-

from __future__ import annotations

from pickle import STOP as STOP_OPCODE


class Dummy:
    def __init__(self) -> None:
        self.attr = "attr"

    def __eq__(self, __o: object) -> bool:
        if not isinstance(__o, Dummy):
            return NotImplemented
        return self.attr == __o.attr


SAMPLES = [
    (4, "positive integer"),
    (-4, "negative integer"),
    (3.14, "float"),
    (1 + 3j, "complex number"),
    (float("-inf"), "-Infinity"),
    (float("+inf"), "Infinity"),
    ("something", "string"),
    (b"something", "bytes"),
    (b"something%sother" % STOP_OPCODE, "bytes with STOP opcode"),
    (True, "True"),
    (False, "False"),
    (None, "None"),
    ([], "empty list"),
    ({}, "empty dict"),
    (int, "type"),
    (int.to_bytes, "method"),
    (Dummy(), "user-defined class instance"),
    (Dummy, "user-defined class type"),
    (
        {
            "data1": True,
            "data2": [
                {
                    "user": "something",
                    "password": "other_thing",
                }
            ],
            "data3": {
                "value": [1, 2, 3, 4],
                "salt": "azerty",
            },
            "data4": 3.14,
            "data5": [
                float("+inf"),
                float("-inf"),
                None,
            ],
        },
        "json-like object",
    ),
]
