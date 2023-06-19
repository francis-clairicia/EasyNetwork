# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any

SAMPLES: list[tuple[Any, str]] = [
    (5, "positive integer"),
    (-123, "negative integer"),
    (1.3, "positive float"),
    (-19.465, "negative float"),
    # (float("nan"), "NaN"),  # Cannot test because NaN is never equal to something else (even itself)
    (float("-inf"), "-Infinity"),
    (float("+inf"), "Infinity"),
    (True, "True"),
    (False, "False"),
    (None, "None"),
    ("", "empty string"),
    ("non-empty", "non-empty string"),
    ("non-empty with é", "non-empty with unicode"),
    ([], "empty list"),
    ({}, "empty dict"),
    ([1, 2, 3], "non-empty list"),
    ({"k": "v", "k2": "v2"}, "non-empty dict"),
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
                None,
            ],
        },
        "json object 1",
    ),
    (
        [{"value": "a"}, {"value": 3.14}, {"value": True}, {"value": {"other": [float("+inf")]}}],
        "json object 2",
    ),
    (
        '[{"value": "a"}, {"value": 3.14}, {"value": True}, {"value": {"other": [float("nan")]}}]',
        "json object 3",
    ),
    (
        {'{"key": [{"key": "value", "key2": [4, 5, -Infinity]}], "other": null}': 42},
        "json object 4",
    ),
]


BIG_JSON: Any = [
    {
        "_id": "63cd615fa31a400f255ec20c",
        "index": 0,
        "guid": "b946bb2d-76f8-41e2-b0a2-905590daa995",
        "isActive": False,
        "balance": "$3,169.85",
        "picture": "http://placehold.it/32x32",
        "age": 37,
        "eyeColor": "blue",
        "name": "Madelyn Kelly",
        "gender": "female",
        "company": "ANIXANG",
        "email": "madelynkelly@anixang.com",
        "phone": "+1 (890) 410-3529",
        "address": "235 Butler Place, Bedias, Tennessee, 2357",
        "about": "Esse voluptate duis labore tempor. Dolor ipsum non fugiat tempor culpa minim quis est cupidatat laboris ut. Consectetur culpa quis dolore ad culpa officia ut. Dolore do aliqua adipisicing est dolore irure eu elit sit minim laboris. Sunt laboris dolore enim incididunt. Ex fugiat consectetur sunt laboris mollit irure dolore.\r\n",
        "registered": "2016-02-26T01:48:27 -01:00",
        "latitude": -89.467862,
        "longitude": -107.644342,
        "tags": ["non", "aliquip", "proident", "est", "adipisicing", "labore", "minim"],
        "friends": [{"id": 0, "name": "Britt Coffey"}, {"id": 1, "name": "Hart Shields"}, {"id": 2, "name": "Simmons Acosta"}],
        "greeting": "Hello, Madelyn Kelly! You have 8 unread messages.",
        "favoriteFruit": "apple",
    },
    {
        "_id": "63cd615f01a4d3d766611021",
        "index": 1,
        "guid": "38afaf5e-a9b1-409c-a982-152b378aa72a",
        "isActive": True,
        "balance": "$3,993.91",
        "picture": "http://placehold.it/32x32",
        "age": 33,
        "eyeColor": "blue",
        "name": "Joanne Wallace",
        "gender": "female",
        "company": "OPTICOM",
        "email": "joannewallace@opticom.com",
        "phone": "+1 (971) 587-3644",
        "address": "449 Cumberland Street, Aberdeen, Delaware, 1752",
        "about": "Nostrud velit ullamco exercitation veniam. Sunt amet sunt cillum consequat ex eiusmod enim exercitation aliqua et laboris anim eiusmod Lorem. Eu non velit duis do culpa cillum sint.\r\n",
        "registered": "2022-09-19T11:00:34 -02:00",
        "latitude": -83.290635,
        "longitude": -104.769739,
        "tags": ["veniam", "incididunt", "commodo", "cillum", "fugiat", "exercitation", "adipisicing"],
        "friends": [{"id": 0, "name": "Byers Bradshaw"}, {"id": 1, "name": "Luella Simpson"}, {"id": 2, "name": "Jennie Ortega"}],
        "greeting": "Hello, Joanne Wallace! You have 5 unread messages.",
        "favoriteFruit": "strawberry",
    },
    {
        "_id": "63cd615fd8c9ef50b325c237",
        "index": 2,
        "guid": "fbfe2d9e-34dd-4069-a040-51137087da7d",
        "isActive": True,
        "balance": "$3,050.13",
        "picture": "http://placehold.it/32x32",
        "age": 30,
        "eyeColor": "green",
        "name": "Lorena Hansen",
        "gender": "female",
        "company": "QUOTEZART",
        "email": "lorenahansen@quotezart.com",
        "phone": "+1 (874) 572-3044",
        "address": "853 Stillwell Place, Chautauqua, Arkansas, 8509",
        "about": "Ut amet minim quis sunt fugiat et fugiat elit consectetur tempor occaecat esse dolore. Dolor eiusmod veniam anim est voluptate adipisicing ut mollit ipsum. Pariatur pariatur laboris laborum quis anim sunt excepteur sunt Lorem sunt ad ullamco minim et. Officia amet aute ipsum ad eu est veniam eu ut irure.\r\n",
        "registered": "2017-05-03T06:14:32 -02:00",
        "latitude": 2.03355,
        "longitude": 22.712443,
        "tags": ["do", "nostrud", "voluptate", "eu", "cupidatat", "excepteur", "exercitation"],
        "friends": [{"id": 0, "name": "Ball Duke"}, {"id": 1, "name": "Hood Hodge"}, {"id": 2, "name": "Helena Pennington"}],
        "greeting": "Hello, Lorena Hansen! You have 7 unread messages.",
        "favoriteFruit": "strawberry",
    },
    {
        "_id": "63cd615ffc1fa91902453aa8",
        "index": 3,
        "guid": "986674c0-0fdd-42a2-a667-8fa6e706bfda",
        "isActive": True,
        "balance": "$1,194.80",
        "picture": "http://placehold.it/32x32",
        "age": 23,
        "eyeColor": "blue",
        "name": "Emerson Vance",
        "gender": "male",
        "company": "NIKUDA",
        "email": "emersonvance@nikuda.com",
        "phone": "+1 (987) 581-3215",
        "address": "371 Cook Street, Rosedale, Puerto Rico, 1264",
        "about": "Pariatur consequat quis amet id commodo proident pariatur laboris. Dolor sit dolore ipsum deserunt amet esse proident. Eu id ad commodo ad elit. Aliqua aliquip nisi qui duis consequat amet cillum reprehenderit in aliqua id dolor pariatur laborum. Tempor id consectetur Lorem sunt. Aliquip officia occaecat nisi nostrud sit eu. Aliqua incididunt ad tempor officia amet mollit.\r\n",
        "registered": "2017-12-31T06:13:24 -01:00",
        "latitude": 71.905823,
        "longitude": 10.495937,
        "tags": ["laboris", "eu", "sunt", "ut", "minim", "do", "exercitation"],
        "friends": [{"id": 0, "name": "Tyler Little"}, {"id": 1, "name": "Hammond Flores"}, {"id": 2, "name": "Cherie Chapman"}],
        "greeting": "Hello, Emerson Vance! You have 7 unread messages.",
        "favoriteFruit": "strawberry",
    },
    {
        "_id": "63cd615fd59ec692a151e788",
        "index": 4,
        "guid": "478cbff2-c8a0-490f-9383-59d0504739f9",
        "isActive": False,
        "balance": "$1,594.36",
        "picture": "http://placehold.it/32x32",
        "age": 32,
        "eyeColor": "green",
        "name": "Briana Aguilar",
        "gender": "female",
        "company": "COMTRAIL",
        "email": "brianaaguilar@comtrail.com",
        "phone": "+1 (903) 403-2600",
        "address": "651 Rochester Avenue, Tecolotito, Wyoming, 5947",
        "about": "Exercitation qui in excepteur in ut aliquip. Aliquip sunt adipisicing excepteur elit mollit nostrud ea exercitation. Occaecat cupidatat pariatur magna velit in adipisicing proident ad do. Esse do dolore sunt deserunt sunt officia veniam non consectetur cupidatat aliqua velit sint tempor.\r\n",
        "registered": "2017-07-16T07:13:28 -02:00",
        "latitude": 75.425314,
        "longitude": -169.397312,
        "tags": ["aliquip", "nulla", "do", "magna", "id", "elit", "veniam"],
        "friends": [{"id": 0, "name": "Zimmerman Medina"}, {"id": 1, "name": "Flossie Fox"}, {"id": 2, "name": "Heather Carney"}],
        "greeting": "Hello, Briana Aguilar! You have 8 unread messages.",
        "favoriteFruit": "banana",
    },
    {
        "_id": "63cd615f8edb42a4d736dbb6",
        "index": 5,
        "guid": "578e7d0f-f51c-40c4-aa8f-3413c293f9a3",
        "isActive": True,
        "balance": "$3,767.74",
        "picture": "http://placehold.it/32x32",
        "age": 23,
        "eyeColor": "blue",
        "name": "Giles Kirkland",
        "gender": "male",
        "company": "ZIPAK",
        "email": "gileskirkland@zipak.com",
        "phone": "+1 (836) 433-2648",
        "address": "205 Kingston Avenue, Welda, Alabama, 3845",
        "about": "Minim cillum elit aliqua deserunt ea aliquip adipisicing. Eiusmod culpa elit velit labore esse enim voluptate ad adipisicing aliquip voluptate proident. Pariatur Lorem non ipsum ex commodo non fugiat. Occaecat aute cupidatat ipsum consectetur qui dolore sit ex velit deserunt veniam. Ea aute reprehenderit irure consequat minim incididunt eiusmod. Aliquip incididunt sunt minim quis labore fugiat pariatur cupidatat fugiat sit aliqua dolore ex labore.\r\n",
        "registered": "2022-09-04T10:41:16 -02:00",
        "latitude": 28.539279,
        "longitude": -59.693012,
        "tags": ["aute", "laboris", "consequat", "elit", "consectetur", "enim", "cupidatat"],
        "friends": [{"id": 0, "name": "Terri Salas"}, {"id": 1, "name": "Contreras Dale"}, {"id": 2, "name": "Catalina Hart"}],
        "greeting": "Hello, Giles Kirkland! You have 3 unread messages.",
        "favoriteFruit": "apple",
    },
    {
        "_id": "63cd615fd1cd188933913791",
        "index": 6,
        "guid": "6100cedf-cc00-45ea-8ebb-b9d9ae7244b0",
        "isActive": False,
        "balance": "$3,389.68",
        "picture": "http://placehold.it/32x32",
        "age": 29,
        "eyeColor": "brown",
        "name": "Hollie Hyde",
        "gender": "female",
        "company": "IDEALIS",
        "email": "holliehyde@idealis.com",
        "phone": "+1 (807) 452-3794",
        "address": "237 Rockaway Avenue, Trinway, South Carolina, 8238",
        "about": "Id ad non velit aliquip id elit excepteur tempor Lorem minim. Eu aliqua amet id enim. Cillum nulla ad aute laborum elit non commodo.\r\n",
        "registered": "2017-10-05T11:40:06 -02:00",
        "latitude": 47.502062,
        "longitude": 9.370487,
        "tags": ["proident", "ad", "proident", "mollit", "cillum", "aliquip", "sit"],
        "friends": [{"id": 0, "name": "Roseann Downs"}, {"id": 1, "name": "Bobbie Peck"}, {"id": 2, "name": "Lacy Dorsey"}],
        "greeting": "Hello, Hollie Hyde! You have 7 unread messages.",
        "favoriteFruit": "strawberry",
    },
]

SAMPLES += [(BIG_JSON, "big json")]
