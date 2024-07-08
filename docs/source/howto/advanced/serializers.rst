********************
How-to — Serializers
********************

.. contents:: Table of Contents
   :local:

------

The Basics
==========

A :term:`serializer` is used by a :term:`protocol object`:

* :class:`.DatagramProtocol`: accepts any :term:`serializer` object.

* :class:`.StreamProtocol`: accepts :term:`incremental serializer` objects only.

.. seealso::

   :doc:`../protocols`
      Describes where and when a :term:`protocol object` is used.


Writing A One-Shot Serializer
=============================

:term:`One-shot serializers <one-shot serializer>` are the easiest piece of code to write. They can be used directly on
:class:`.DatagramProtocol` instances.

To write a :term:`one-shot serializer`, you must create a subclass of :class:`~.AbstractPacketSerializer` and override
its :meth:`~.AbstractPacketSerializer.serialize` and :meth:`~.AbstractPacketSerializer.deserialize` methods.

A naive implementation of :class:`.JSONSerializer` should look something like this:

.. literalinclude:: ../../_include/examples/howto/serializers/one_shot_serializer/example1.py
   :linenos:


Parsing Error
-------------

The :meth:`~.AbstractPacketSerializer.deserialize` function must raise a :exc:`.DeserializeError` to indicate that a parsing error
was "expected" so that the received data is considered invalid.

.. literalinclude:: ../../_include/examples/howto/serializers/one_shot_serializer/example2.py
   :linenos:
   :emphasize-lines: 6,19,22-23

.. warning::

   Otherwise, any other error is considered a serializer crash.


The Use Of ``self``
-------------------

A :term:`serializer` is intended to be shared by multiple :term:`protocols <protocol object>` (and :term:`protocols <protocol object>` are intended
to be shared by multiple endpoints).

Therefore, the object should only store additional configuration used for serialization/deserialization.

For example:

.. literalinclude:: ../../_include/examples/howto/serializers/one_shot_serializer/example3.py
   :pyobject: MyJSONSerializer
   :linenos:

.. warning::

   Do not store per-serialization data. You might see some magic.

.. danger::

   Seriously, don't do that.


Using A One-Shot Serializer
---------------------------

You must pass the :term:`serializer` to the appropriate :term:`protocol object` that is expected by the endpoint class:

.. tabs::

   .. group-tab:: DatagramProtocol

      .. literalinclude:: ../../_include/examples/howto/serializers/one_shot_serializer/example4_datagram.py
         :pyobject: main
         :linenos:

   .. group-tab:: StreamProtocol

      A :term:`one-shot serializer` cannot be used with a :class:`.StreamProtocol` instance.

      .. seealso::

         :doc:`./serializer_combinations`
            This page explains possible workarounds which uses serializer wrappers.

      .. note::

         Using a :term:`serializer wrapper` means that the transferred data can be completely different from the original output.

         If this is important to you, don't choose one of them lightly.


Writing An Incremental Serializer
=================================

:term:`Incremental serializers <incremental serializer>` are a bit trickier to implement. They can be used directly on both
:class:`.StreamProtocol` and :class:`.DatagramProtocol` instances.

To write an :term:`incremental serializer`, you must create a subclass of :class:`~.AbstractIncrementalPacketSerializer` and override
its :meth:`~.AbstractIncrementalPacketSerializer.incremental_serialize` and :meth:`~.AbstractIncrementalPacketSerializer.incremental_deserialize`
methods. The :meth:`~.AbstractIncrementalPacketSerializer.serialize` and :meth:`~.AbstractIncrementalPacketSerializer.deserialize` methods
have a default implementation that uses the incremental serialization methods.

Option 1: Using Common Patterns
-------------------------------

Chances are that the communication protocol uses a simple principle to determine the end of a packet. The most common cases are:

* All your packet frames use a precise byte sequence (most likely a newline).

* Each packet has a fixed size.

In these cases you can use the base classes in :mod:`easynetwork.serializers.base_stream`.

Let's say that for the incremental part, we consider each line received to be a JSON object, separated by ``\r\n``:

.. literalinclude:: ../../_include/examples/howto/serializers/incremental_serializer/example1.py
   :linenos:
   :emphasize-lines: 7,13,15

:class:`.AutoSeparatedPacketSerializer` adds the following behaviors:

* ``incremental_serialize()`` will append ``\r\n`` to the end of the ``serialize()`` output.

* ``incremental_deserialize()`` waits until ``\r\n`` is found in the input, removes the separator, and calls ``deserialize()`` on it.

.. tip::

   Take a look at other available base classes in :mod:`easynetwork.serializers` before rewriting something that already exists.


Option 2: From Scratch
----------------------

Let's see how we can get by without using the :class:`.AutoSeparatedPacketSerializer`:

.. collapse:: Click here to expand/collapse the full code

   .. literalinclude:: ../../_include/examples/howto/serializers/incremental_serializer/example2.py
      :linenos:
      :emphasize-lines: 8,14,22-28,39-


Code Mutualization
^^^^^^^^^^^^^^^^^^

To avoid duplication of code between the one-shot part and the incremental part,
the serialization/deserialization part of the code goes to a private method.

.. literalinclude:: ../../_include/examples/howto/serializers/incremental_serializer/example2.py
   :start-at: def _dump
   :end-at: return json.loads
   :dedent:
   :lineno-match:

And now ``serialize()`` and ``deserialize()`` use them instead:

.. literalinclude:: ../../_include/examples/howto/serializers/incremental_serializer/example2.py
   :start-at: def serialize
   :end-at: raise DeserializeError
   :dedent:
   :lineno-match:
   :emphasize-lines: 2,6

The Purpose Of ``incremental_serialize()``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:meth:`~.AbstractIncrementalPacketSerializer.incremental_serialize` must be a :term:`generator` function
(or at least return a :term:`generator iterator`) that yields all the parts of the serialized packet.
It must also add any useful metadata to help :meth:`~.AbstractIncrementalPacketSerializer.incremental_deserialize` find the end of the packet.

.. literalinclude:: ../../_include/examples/howto/serializers/incremental_serializer/example2.py
   :pyobject: MyJSONSerializer.incremental_serialize
   :dedent:
   :lineno-match:

Most of the time, you will have a single :keyword:`yield`. The goal is: each :keyword:`yield` must send as many :class:`bytes` as possible
**without copying or concatenating**.

.. tip::

   There may be exceptions, like this example. (Your RAM will not cry because you added 2 bytes to a byte sequence of almost 100 bytes.
   The question may be asked if the byte sequence is ending up to 4 GB.)

   It is up to you to find the balance between RAM explosion and performance degradation.

.. note::

   The endpoint implementation can decide to concatenate all the pieces and do one big send. However, it may be more attractive to do something else
   with the returned bytes. :meth:`~.AbstractIncrementalPacketSerializer.incremental_serialize` is here to give endpoints this freedom.


The Purpose Of ``incremental_deserialize()``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:meth:`~.AbstractIncrementalPacketSerializer.incremental_deserialize` must be a :term:`generator` function
(or at least return a :term:`generator iterator`) that yields :data:`None` until all the data parts of the packet have been retrieved and parsed.

This generator must return a pair of ``(packet, remainder)`` where ``packet`` is the deserialized packet and ``remainder`` is any
superfluous trailing bytes that was useless.

At each :keyword:`yield` checkpoint, the endpoint implementation sends to the generator the data received from the remote endpoint.

.. literalinclude:: ../../_include/examples/howto/serializers/incremental_serializer/example2.py
   :pyobject: MyJSONSerializer.incremental_deserialize
   :dedent:
   :lineno-match:
   :emphasize-lines: 2,5

.. note::

   Even if we could create 5 more JSON packets from ``remainder``, ``incremental_deserialize()`` must always deserialize the first one available
   and return the rest **as is**.

   This allows the endpoint implementation to deserialize only the needed packet. The rest is reused when the application wants an other packet.

.. seealso::

   :doc:`/api/serializers/tools`
      Regroups helpers for (incremental) serializer implementations.

   :pep:`255` — Simple Generators
      The proposal for adding generators and the :keyword:`yield` statement to Python.

   :pep:`342` — Coroutines via Enhanced Generators
      The proposal to enhance the API and syntax of generators, making them usable as simple coroutines.

   :pep:`380` — Syntax for Delegating to a Subgenerator
      The proposal to introduce the ``yield from`` syntax, making delegation to subgenerators easy.


Parsing Error
^^^^^^^^^^^^^

The :meth:`~.AbstractIncrementalPacketSerializer.incremental_deserialize` function must raise an :exc:`.IncrementalDeserializeError`
to indicate that a parsing error was "expected" so that the received data is considered invalid.

.. literalinclude:: ../../_include/examples/howto/serializers/incremental_serializer/example2.py
   :pyobject: MyJSONSerializer.incremental_deserialize
   :dedent:
   :lineno-match:
   :emphasize-lines: 12-13

.. warning::

   Otherwise, any other error is considered a serializer crash.

   If :exc:`.DeserializeError` is raised instead, this is converted to a :exc:`RuntimeError`.

.. note::

   :exc:`.IncrementalDeserializeError` needs the possible valid remainder, that is not the root cause of the error.
   In the example, even if ``data`` is an invalid JSON object, all bytes after the ``\r\n`` token (in ``remainder``) are not lost.


Using An Incremental Serializer
-------------------------------

Now our :term:`serializer` can be used with a stream :term:`protocol object`:

.. tabs::

   .. group-tab:: StreamProtocol

      .. literalinclude:: ../../_include/examples/howto/serializers/incremental_serializer/example3_stream.py
         :pyobject: main
         :linenos:
