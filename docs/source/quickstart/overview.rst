Overview
========

EasyNetwork fully encapsulates socket handling, offering you a high-level interface enabling an application/software to fully handle the logic part
with Python objects without worrying about how to process, send or receive data across the network.

The communication protocol can be whatever you want, be it json, pickle, ASCII, structure, base64 encoded, compressed, encrypted,
or any other format not part of the standard library.
You choose the data format, and the library takes care of the rest.


Works with TCP and UDP, for Internet sockets (:data:`socket.AF_INET` and :data:`socket.AF_INET6` families).

.. warning::

   Unix sockets (:data:`socket.AF_UNIX` family) are expressly *not* supported.
