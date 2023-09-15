*********************
Abstract Base Classes
*********************

.. contents:: Table of Contents
   :local:

------

Top-Level Base Classes
======================

.. automodule:: easynetwork.serializers.abc
   :no-docstring:

.. autoclass:: AbstractPacketSerializer
   :members:

.. autoclass:: AbstractIncrementalPacketSerializer
   :members:


------

Stream Base Classes
===================

.. automodule:: easynetwork.serializers.base_stream
   :no-docstring:

Here are abstract classes that implement common stream protocol patterns.

.. autoclass:: AutoSeparatedPacketSerializer
   :members:

.. autoclass:: FixedSizePacketSerializer
   :members:

.. autoclass:: FileBasedPacketSerializer
   :members:
