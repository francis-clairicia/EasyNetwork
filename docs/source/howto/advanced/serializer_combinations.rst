********************************
How-to — Serializer Combinations
********************************

.. contents:: Table of Contents
   :local:

------

The Basics
==========

In order to extend the use of serializers, it is possible to use serializers **that wrap other serializers**.
The goal is to customize the behavior of the serialized data without even knowing what is in it.

For example, you could:

* compress the data

* add a checksum to verify data integrity

* encode/encrypt the data

* and much more.

Such a class is called a :term:`serializer wrapper`.
The :mod:`easynetwork.serializers.wrapper` package provides some useful classes to handle these cases.


Use Cases
=========

To illustrate why this concept exists and can be useful to you, let's take a concrete example of an existing serializer.

Let's say we have a serializer named... :class:`.PickleSerializer`.

Enable The Stream Context
-------------------------

There is no efficient way to determine the end of a pickle-serialized object without calling :func:`pickle.loads` and praying that it works.
And since we're running Python code to recursively deserialize objects, it's even less safe to potentially deserialize by half.

Therefore, this class does not implement the :class:`.AbstractIncrementalPacketSerializer` class.
But if we want to use stream pipes (at random, a TCP stream), how can we do that?

Fortunately, it is possible to encode pickle data in another format: :mod:`base64`.
Using an alphabet, we can divide the received packets into lines. And this is exactly what the :class:`.Base64EncoderSerializer` already does:

.. literalinclude:: ../../_include/examples/howto/serializers/serializer_combinations/example1.py
   :pyobject: main
   :linenos:
   :emphasize-lines: 6


Ensure Data Integrity
---------------------

The :mod:`pickle` protocol is incredibly handy, but not very secure. Aside from the fact that malicious data can be processed,
it can also be corrupted in transit, which is even more problematic since :mod:`pickle` relies on data to execute code, not the other way around.

To overcome this, we can tell the serializer to add an extra layer of verification:

.. literalinclude:: ../../_include/examples/howto/serializers/serializer_combinations/example2.py
   :pyobject: main
   :linenos:
   :emphasize-lines: 5


Use Less Bandwidth
------------------

Let's say ``{"data": 42}`` produces a BIG packet (e.g., 1Mb size).

This is often the case with large projects that handle a lot of data.
It's common practice to reduce the size of packets sent as much as possible to reduce bandwidth usage and network traffic.

The first thing to do would be to reduce the pickle data itself:

.. literalinclude:: ../../_include/examples/howto/serializers/serializer_combinations/example3.py
   :pyobject: main
   :linenos:
   :emphasize-lines: 5

This will do the trick, but it's clearly not enough. So, last option: compress the data using :mod:`zlib`.

.. literalinclude:: ../../_include/examples/howto/serializers/serializer_combinations/example4.py
   :pyobject: main
   :linenos:
   :emphasize-lines: 2,4,8


Deserialize Trusted Data
------------------------

Adding a checksum to verify the data is all well and good,
but it's not enough in terms of security if there's no authentication protocol to ensure the provenance of the data,
and even less so when it comes to :mod:`pickle`.

The last thing to do would be to add a signature with a key known only to the two communicators.

.. literalinclude:: ../../_include/examples/howto/serializers/serializer_combinations/example5.py
   :pyobject: main
   :linenos:
   :emphasize-lines: 7,10

Now we use this :class:`.StreamProtocol` for both server and client, and we can have secure data transfer.
