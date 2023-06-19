# -*- coding: utf-8 -*-

from __future__ import annotations

from pickle import STOP as STOP_OPCODE


class Dummy:
    def __init__(self) -> None:
        self.attr = "attr"

    def __eq__(self, __o: object) -> bool:
        if not isinstance(__o, Dummy):
            return NotImplemented
        return self.attr == __o.attr


class BigDummy:
    def __init__(self, level: int) -> None:
        assert level > 0
        level -= 1
        if level == 0:
            self.dummy = {}
        else:
            self.dummy = {
                "dummy1": BigDummy(level),
                "dummy2": {
                    "subdummy1": BigDummy(level),
                    "subdummy2": [BigDummy(level) for _ in range(10)],
                },
                "dummy3": [
                    {
                        "subdummy1": [BigDummy(level) for _ in range(5)],
                        "subdummy2": {
                            "sub-subdummy": BigDummy(level),
                        },
                    }
                    for _ in range(20)
                ],
            }

    def __eq__(self, __o: object) -> bool:
        if not isinstance(__o, BigDummy):
            return NotImplemented
        return self.dummy == __o.dummy


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
    (BigDummy(level=1), "big object"),
]
