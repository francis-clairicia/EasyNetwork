***********
Serializers
***********

.. automodule:: easynetwork.serializers

.. contents:: Table of Contents
   :local:


------


Base classes
============

.. autoclass:: easynetwork.serializers.AbstractPacketSerializer
   :members:

.. autoclass:: easynetwork.serializers.AbstractIncrementalPacketSerializer
   :members:


------


Stream base classes
===================

Here are abstract classes that implement common stream protocol patterns.

.. autoclass:: easynetwork.serializers.AutoSeparatedPacketSerializer
   :members:

.. autoclass:: easynetwork.serializers.FixedSizePacketSerializer
   :members:

.. autoclass:: easynetwork.serializers.FileBasedPacketSerializer
   :members:


------


JSON serializer
===============

.. autoclass:: easynetwork.serializers.JSONSerializer
   :members:

JSON serializer configuration
-----------------------------

.. autoclass:: easynetwork.serializers.JSONEncoderConfig
   :members:

.. autoclass:: easynetwork.serializers.JSONDecoderConfig
   :members:


------


Pickle serializer
=================

.. warning::

   Read the security considerations for using :mod:`pickle` module.

.. todo::

   Add examples of how to use PickleSerializer with EncryptorSerializer or Base64EncoderSerializer with checksum.

.. autoclass:: easynetwork.serializers.PickleSerializer
   :members:

Pickle serializer configuration
-------------------------------

.. autoclass:: easynetwork.serializers.PicklerConfig
   :members:

.. autoclass:: easynetwork.serializers.UnpicklerConfig
   :members:


------


String serializer
=================

.. autoclass:: easynetwork.serializers.StringLineSerializer
   :members:


------


Structure serializer
====================

Serializers that use the :mod:`struct` module.

There is a base class :class:`.AbstractStructSerializer` to easily manipulate structured data.

.. autoclass:: easynetwork.serializers.AbstractStructSerializer
   :members:

.. autoclass:: easynetwork.serializers.NamedTupleStructSerializer
   :members:


------


CBOR serializer
===============

The `CBOR <https://cbor.io>`_ is an alternative representation of the ``JSON`` data models.

.. include:: ../_include/see-also-optional-dependencies.rst

.. autoclass:: easynetwork.serializers.CBORSerializer
   :members:

CBOR serializer configuration
-----------------------------

.. autoclass:: easynetwork.serializers.CBOREncoderConfig
   :members:

.. autoclass:: easynetwork.serializers.CBORDecoderConfig
   :members:


------


MessagePack serializer
======================

The `MessagePack <https://msgpack.org/>`_ is an alternative representation of the ``JSON`` data models.

.. include:: ../_include/see-also-optional-dependencies.rst

.. autoclass:: easynetwork.serializers.MessagePackSerializer
   :members:

MessagePack serializer configuration
------------------------------------

.. autoclass:: easynetwork.serializers.MessagePackerConfig
   :members:

.. autoclass:: easynetwork.serializers.MessageUnpackerConfig
   :members:
