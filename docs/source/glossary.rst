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

   protocol object
      An object representing a :term:`communication protocol`. It consists of a :term:`serializer` and, optionally, a :term:`converter`.

   serializer
      A serializer is the lowest layer for passing from a Python object to raw data (:py:class:`bytes`) and vice versa.

      It must have no knowledge of the object's validity, nor of the application/software's logic. This ensures a generic format that can be reused in any project.

      For example, the ``JSONSerializer`` only knows how to translate dictionaries, lists, strings and numbers, and how to reinterpret them.

      A serializer imposes its own limits on the objects it can translate and on the validity of the object itself
      (for example, for a JSON, a dictionary must only have character strings as keys).

      There are 2 types of serializers:

      * one-shot serializers

        One-shot serializers provide the full representation of a Python object in bytes **in a single function call**,
        and need this same full representation to recreate the object **at once**.

        .. note::

           They are particularly useful for datagram communication (e.g. `UDP`_).

      * incremental serializers

        Incremental serializers, on the other hand, provide the representation of the Python object in bytes **part by part**
        (or directly at once if the underlying API does not provide incremental support).

        During deserialization, they have the ability **to know when the data is complete** (and wait if incomplete)
        and which data are not part of the initial "packet".

        .. note::

           They are particularly useful for connection-oriented stream communication (e.g. `TCP`_).

        .. note::

           They are de facto "one shot" serializers too.

      .. todo::

         Add a "See also" section to go in "How to write a serializer ?"

.. Links

.. _UDP: https://en.wikipedia.org/wiki/User_Datagram_Protocol

.. _TCP: https://en.wikipedia.org/wiki/Transmission_Control_Protocol
