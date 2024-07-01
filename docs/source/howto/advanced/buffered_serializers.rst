*****************************
How-to — Buffered Serializers
*****************************

.. contents:: Table of Contents
   :local:

------

Introduction
============

:meth:`~.AbstractIncrementalPacketSerializer.incremental_deserialize` is useful to wait for all data parts of a packet,
but there is a small problem with it: the memory consumption.

The Actual Behavior
-------------------

What happens when you hit a :keyword:`yield` statement:

* A large enough byte buffer is allocated (one call to :manpage:`malloc(3)`).

* :manpage:`recv(2)` will write as much as possible to this buffer.

* The byte buffer is shrunk to fit the bytes actually written (one call to :manpage:`realloc(3)`).

* This finished :class:`bytes` instance is sent to the generator.

What are you likely to do with this byte buffer:

* Append the content to an existing byte buffer, which can be:

  * a :class:`bytes` (involves a call to :manpage:`malloc(3)` and then :manpage:`free(3)`).

  * a :class:`bytearray` (involves a call to :manpage:`realloc(3)`).

  * a custom stream-like API such as :class:`io.BytesIO` (involves a call to :manpage:`realloc(3)`).

  * or something else, but which will somehow do one of the things above.

* Drop the reference to the given byte buffer, since you no longer need it (one call to :manpage:`free(3)`).

Now Imagine That...
-------------------

...you want :manpage:`recv(2)` to write directly to *your* byte buffer (and perhaps at a given position).

It might look like this:

* :manpage:`recv(2)` will write as much as possible to the byte buffer *you* provided.

* The number of bytes written is sent to the generator.

This principle involves several things:

* The byte buffer can be reused (so there is no more buffer allocation per :manpage:`recv(2)` call).

* It is no longer necessary to copy the content to another location.

This is what the :class:`.BufferedIncrementalPacketSerializer` is designed for.

The benefits?
-------------

This model exists for performance purposes only. However, it requires careful consideration of the needs to be met.
It's not a quick fix that will solve application performance problems. In fact, it may not be convenient.

The scenario described above is a real problem for **servers** with high workloads and/or low bandwidth
that exchange large amounts of data with their clients. In such a situation, the slightest typo can bring
the whole thing crashing down. Under "normal" conditions, the basic implementation is more than enough
to keep a server running with acceptable performance.

.. important::

   I want to point out that it's not about speed. It may slow the server down a bit, but it will be more robust.

------

Usage
=====

For the serializers that support this API, you must use :class:`.BufferedStreamProtocol` instead of :class:`.StreamProtocol`:

.. literalinclude:: ../../_include/examples/howto/protocols/usage/buffered_stream_protocol.py
   :pyobject: main
   :linenos:
   :emphasize-lines: 3

Writing A Buffered Serializer
=============================

To write a :term:`buffered serializer`, you must create a subclass of :class:`~.BufferedIncrementalPacketSerializer` and override
its :meth:`~.BufferedIncrementalPacketSerializer.create_deserializer_buffer` and
:meth:`~.BufferedIncrementalPacketSerializer.buffered_incremental_deserialize` methods.

.. note::

   You still need to implement :class:`.AbstractIncrementalPacketSerializer` methods.

Let's see how we can use it for ``MyJSONSerializer`` (from :doc:`./serializers`):

.. collapse:: Click here to expand/collapse the full code

   .. literalinclude:: ../../_include/examples/howto/serializers/buffered_incremental_serializer/example1.py
      :linenos:
      :emphasize-lines: 8,17,63-


Choose the buffer type
----------------------

When subclassing :class:`.BufferedIncrementalPacketSerializer`, you must pass the buffer type. This should be the type of the instance returned
by :meth:`~.BufferedIncrementalPacketSerializer.create_deserializer_buffer`.

A buffer object is an object that implements the :ref:`buffer protocol <bufferobjects>`.

.. tip::

   As of Python 3.12, a buffer object can also be an object that implements the :class:`collections.abc.Buffer` interface.

For the tutorial, we use a :class:`bytearray`:

.. literalinclude:: ../../_include/examples/howto/serializers/buffered_incremental_serializer/example1.py
   :end-at: class MyJSONSerializer
   :dedent:
   :lineno-match:
   :emphasize-lines: 8,17

.. _buffer-instantiation:

Buffer Instantiation
--------------------

.. literalinclude:: ../../_include/examples/howto/serializers/buffered_incremental_serializer/example1.py
   :pyobject: MyJSONSerializer.create_deserializer_buffer
   :dedent:
   :lineno-match:

.. note::

   ``sizehint`` is the *recommended* buffer size, but the buffer can be of any size.

   In the example, we assume that a JSON line can be up to 64KiB. Therefore, the minimum buffer size must be 64KiB.

.. important::

   This function is called **only once per connection**. This means that
   :meth:`~.BufferedIncrementalPacketSerializer.buffered_incremental_deserialize` will reuse the same buffer for a given stream.

The Purpose Of ``buffered_incremental_deserialize()``
-----------------------------------------------------

:meth:`~.BufferedIncrementalPacketSerializer.buffered_incremental_deserialize` must be a :term:`generator` function
(or at least return a :term:`generator iterator`) that yields until all the data parts of the packet have been retrieved and parsed.

The value yielded is the position to start writing to the buffer. It can be:

* :data:`None`: Just use the whole buffer. Therefore, ``yield`` and ``yield None`` are equivalent to ``yield 0``.

* A positive integer (starting at ``0``): Skips the first *n* bytes.

* A negative integer: Skips until the last *n* bytes. For example, ``yield -10`` means to write from the last 10th byte of the buffer.

This generator must return a pair of ``(packet, remainder)`` where ``packet`` is the deserialized packet and ``remainder`` is any
superfluous trailing bytes that was useless.
The remainder can be a :class:`memoryview` pointing to ``buffer`` or an external :term:`bytes-like object`.

At each :keyword:`yield` checkpoint, the endpoint implementation sends to the generator the number of bytes written to the ``buffer``
**from the given start position**.

.. literalinclude:: ../../_include/examples/howto/serializers/buffered_incremental_serializer/example1.py
   :pyobject: MyJSONSerializer.buffered_incremental_deserialize
   :dedent:
   :lineno-match:

.. warning::

   Buffer consistency
      Because of buffer reuse, it is up to you to reset the buffer state upon entry and exit of the generator.
      If you are relying only on the area that has already been written, you can skip this step (as in the example above).

   Growing buffers
      It is not supported to increase/decrease the buffer size during deserialization.

.. tip::

   Buffer initialization
      :meth:`~.BufferedIncrementalPacketSerializer.buffered_incremental_deserialize` is called *before* the read.
      You can reinitialize the buffer (for example, by filling it to zero) before the first read::

         def buffered_incremental_deserialize(self, buffer: bytearray) -> Generator[...]:
             for i in range(len(buffer)):
                 buffer[i] = 0

             nbytes = yield

             ...

   Start writing anytime, anywhere
      It is **not** mandatory to yield :data:`None` or ``0`` for the first yield.

   Avoid copying data as much as possible
      :class:`memoryview` is your best friend, use it.


Tips & Tricks
=============

Common implementations between ``incremental_deserialize()`` and ``buffered_incremental_deserialize()``
-------------------------------------------------------------------------------------------------------

If the API you are using does not care about using :class:`bytes` or :class:`memoryview`,
you can write a single function that handles any byte buffer:

.. literalinclude:: ../../_include/examples/howto/serializers/buffered_incremental_serializer/example2.py
   :linenos:
