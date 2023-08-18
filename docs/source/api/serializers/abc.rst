*********************
Abstract base classes
*********************

.. contents:: Table of Contents
   :local:

------

Top-level base classes
======================

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
