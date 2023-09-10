********************************
How-to — Communication protocols
********************************

.. contents:: Table of Contents
   :local:

------

The basics
==========

To define your :term:`communication protocol`, you must instantiate one of the following :term:`protocol objects <protocol object>`:

* :class:`.DatagramProtocol`: suitable for datagram oriented communication (e.g. `UDP`_).

* :class:`.StreamProtocol`: suitable for stream oriented communication (e.g. `TCP`_).

They all have one thing in common: they wrap a :term:`serializer` and a :term:`converter`.

You can either directly create an instance:

.. tabs::

   .. group-tab:: DatagramProtocol

      .. literalinclude:: ../_include/examples/howto/protocols/basics/datagram_protocol_instance.py
         :linenos:

   .. group-tab:: StreamProtocol

      .. literalinclude:: ../_include/examples/howto/protocols/basics/stream_protocol_instance.py
         :linenos:

or do a subclass:

.. tabs::

   .. group-tab:: DatagramProtocol

      .. literalinclude:: ../_include/examples/howto/protocols/basics/datagram_protocol_subclass.py
         :linenos:

   .. group-tab:: StreamProtocol

      .. literalinclude:: ../_include/examples/howto/protocols/basics/stream_protocol_subclass.py
         :linenos:

.. _why-write-a-protocol-subclass:

.. tip::

   The latter is recommended. The main advantage of this model is to declaratively define the :term:`communication protocol`
   (the name of the class being that of the protocol, the types of objects sent and received, etc.).

   Another advantage is that the :term:`serializer` (and :term:`converter`, if any) can be configured in a single place in the project.


Usage
=====

The :term:`protocol objects <protocol object>` are requested by endpoint and server implementations to handle the data sent and received:

.. tabs::

   .. group-tab:: DatagramProtocol

      .. literalinclude:: ../_include/examples/howto/protocols/usage/datagram_protocol.py
         :pyobject: main
         :linenos:

   .. group-tab:: StreamProtocol

      .. literalinclude:: ../_include/examples/howto/protocols/usage/stream_protocol.py
         :pyobject: main
         :linenos:

.. warning::

   A :term:`protocol object` is intended to be shared by multiple endpoints. Do not store sensitive data in these objects.
   You might see some magic.


The converters
==============

TL;DR: Why should you always have a converter in your protocol object?
----------------------------------------------------------------------

Unless the :term:`serializer` is already making the tea and coffee for you, in 99% of cases the data received can be anything,
as long as it's in the right format. On the other hand, the application has to comply with the format for sending data to the remote endpoint.

However, you just want to be able to manipulate your business objects without having to worry about such problems.

This is what a :term:`converter` can do for you. It creates a :term:`DTO` suitable for the underlying :term:`serializer` and validates the received
:term:`DTO` to recreate the business object.

Write a converter
-----------------

To write a :term:`converter`, you must create a subclass of :class:`~.AbstractPacketConverter` and override
its :meth:`~.AbstractPacketConverter.convert_to_dto_packet` and :meth:`~.AbstractPacketConverter.create_from_dto_packet` methods.

For example:

.. literalinclude:: ../_include/examples/howto/protocols/simple_converter/example1.py
   :linenos:

.. warning::

   The :meth:`~.AbstractPacketConverter.create_from_dto_packet` function must raise a :exc:`PacketConversionError` to indicate that
   a parsing error was "expected" so that the received data is considered invalid.

   Otherwise, any other error is considered a crash.

This :term:`converter` can now be used in our :term:`protocol object`:

.. literalinclude:: ../_include/examples/howto/protocols/simple_converter/example2.py
   :pyobject: PersonProtocol
   :linenos:

.. note::

   Now this protocol is annotated to send and receive a ``Person`` object.

In the application, you can now safely handle an object with real meaning:

.. literalinclude:: ../_include/examples/howto/protocols/simple_converter/example2.py
   :pyobject: main
   :linenos:


.. include:: ../_include/link-labels.rst
