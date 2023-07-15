Glossary
========

.. glossary::
   :sorted:

   communication protocol
      A communication protocol is a set of formal rules describing how to transmit or exchange data, especially across a network.

      In EasyNetwork, it's up to the developer to define his communication protocol using a :term:`protocol object`.

   converter
      An object responsible for bridging the gap between the Python objects manipulated by the application/software
      and the objects handled by the :term:`serializer`.

      It must also ensure that deserialized objects are valid and usable by the application/software without post-processing.

   incremental serializer
      See :term:`serializer`.

   one-shot serializer
      See :term:`serializer`.

   packet
      A packet is a unit of data routed between an origin and a destination on a network.

   protocol object
      An object representing a :term:`communication protocol`. It consists of a :term:`serializer` and, optionally, a :term:`converter`.

   serializer
      A serializer is the lowest layer for passing from a Python object to raw data (:class:`bytes`) and vice versa.

      It must have no knowledge of the object's validity with regard to the application/software logic,
      nor the meaning of data with regard to the :term:`communication protocol`.
      This ensures a generic format that can be reused in any project.

      For example, the ``JSONSerializer`` only knows how to translate dictionaries, lists, strings, numbers and special constants,
      and how to reinterpret them.

      A serializer imposes its own limits on the objects it can translate and on the validity of the object itself
      (for example, as a JSON object, a dictionary must only have character strings as keys).

      Ideally, a serializer should only handle :ref:`primitive types <bltin-types>` and :ref:`constants <built-in-consts>`.

      There are 2 types of serializers:

      * one-shot serializers

        One-shot serializers provide the full representation of a Python object in :class:`bytes` **in a single function call**,
        and need this same full representation to recreate the object **at once**.

        .. note::

           They are particularly useful for datagram communication (e.g. `UDP`_).

      * incremental serializers

        Incremental serializers, on the other hand, provide the full representation of the Python object in :class:`bytes` **part by part**,
        sometimes including additional metadata used during deserialization.

        During deserialization, they have the ability **to know when the** :term:`packet` **is complete** (and wait if incomplete)
        and which bytes are not part of the initial :term:`packet`.

        .. note::

           They are particularly useful for connection-oriented stream communication (e.g. `TCP`_).

        .. note::

           They are de facto "one shot" serializers too.

.. Links

.. _UDP: https://en.wikipedia.org/wiki/User_Datagram_Protocol

.. _TCP: https://en.wikipedia.org/wiki/Transmission_Control_Protocol
