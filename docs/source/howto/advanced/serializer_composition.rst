*******************************
How-to — Serializer Composition
*******************************

.. contents:: Table of Contents
   :local:

------

The Basics
==========

A :term:`composite serializer` fulfills the same need as a :term:`composite converter`,
which is to handle two disjoint formats between sent and received packet data.

This is typically done using the :class:`.StapledPacketSerializer`:

>>> import pickle
>>> from easynetwork.serializers import *
>>> from easynetwork.serializers.composite import *
>>> s = StapledPacketSerializer(sent_packet_serializer=PickleSerializer(), received_packet_serializer=JSONSerializer())
>>> s.deserialize(b'{"data": 42}')
{'data': 42}
>>> data = s.serialize({"data": 42})
>>> pickle.loads(data)
{'data': 42}

:class:`.StapledPacketSerializer` will return the correct implementation according to
the base class of ``sent_packet_serializer`` and ``received_packet_serializer``:

>>> from easynetwork.serializers.abc import *
>>>
>>> StapledPacketSerializer(sent_packet_serializer=PickleSerializer(), received_packet_serializer=JSONSerializer())
StapledPacketSerializer(...)
>>> isinstance(_, (AbstractIncrementalPacketSerializer, BufferedIncrementalPacketSerializer))
False
>>>
>>> StapledPacketSerializer(sent_packet_serializer=StringLineSerializer(), received_packet_serializer=JSONSerializer())
StapledIncrementalPacketSerializer(...)
>>> isinstance(_, AbstractIncrementalPacketSerializer)
True
>>>
>>> StapledPacketSerializer(sent_packet_serializer=JSONSerializer(), received_packet_serializer=StringLineSerializer())
StapledBufferedIncrementalPacketSerializer(...)
>>> isinstance(_, BufferedIncrementalPacketSerializer)
True


Use Case: Different Structure Between A Request And A Response
==============================================================

>>> from typing import NamedTuple
>>> from easynetwork.serializers import NamedTupleStructSerializer
>>> from easynetwork.serializers.composite import StapledPacketSerializer
>>> class Request(NamedTuple):
...     type: int
...     data: bytes
...
>>> class Response(NamedTuple):
...     rc: int
...     message: str
...
>>> s = StapledPacketSerializer(
...     sent_packet_serializer=NamedTupleStructSerializer(Request, {"type": "B", "data": "1024s"}, encoding=None),
...     received_packet_serializer=NamedTupleStructSerializer(Response, {"rc": "h", "message": "10s"}, encoding="utf8"),
... )
>>> s.serialize(Request(type=42, data=b"some data to send"))
b'*some data to send\x00\x00\x00\x00\x00...'
>>> s.deserialize(b"\x00\xc8OK\x00\x00\x00\x00\x00\x00\x00\x00")
Response(rc=200, message='OK')
