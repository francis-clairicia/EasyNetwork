***********
Serializers
***********

.. automodule:: easynetwork.serializers

.. contents:: Table of Contents
   :local:

Base classes
============

.. autoclass:: easynetwork.serializers.AbstractPacketSerializer
   :members:

.. autoclass:: easynetwork.serializers.AbstractIncrementalPacketSerializer
   :members:


Stream base classes
===================

Here are abstract classes that implement common stream protocol patterns.

.. autoclass:: easynetwork.serializers.AutoSeparatedPacketSerializer
   :members:

.. autoclass:: easynetwork.serializers.FixedSizePacketSerializer
   :members:

.. autoclass:: easynetwork.serializers.FileBasedPacketSerializer
   :members:


JSON serializer
===============

.. autoclass:: easynetwork.serializers.JSONSerializer
   :members:

Parameter objects
-----------------

.. autoclass:: easynetwork.serializers.JSONEncoderConfig
   :members:

.. autoclass:: easynetwork.serializers.JSONDecoderConfig
   :members:


Pickle serializer
=================

.. warning::

   Read the security considerations for using :mod:`pickle` module.

.. todo::

   Add examples of how to use PickleSerializer with EncryptorSerializer or Base64EncoderSerializer with checksum.

.. autoclass:: easynetwork.serializers.PickleSerializer
   :members:

Parameter objects
-----------------

.. autoclass:: easynetwork.serializers.PicklerConfig
   :members:

.. autoclass:: easynetwork.serializers.UnpicklerConfig
   :members:
