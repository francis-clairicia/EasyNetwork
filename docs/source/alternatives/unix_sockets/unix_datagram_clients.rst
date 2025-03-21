********************************************
Alternative — Unix Datagram Client Endpoints
********************************************

.. include:: ../../_include/sync-async-variants.rst

.. contents:: Table of Contents
   :local:

------

The Protocol Object
===================

The UNIX datagram clients expect a :class:`.DatagramProtocol` instance to communicate with the peer endpoint.

.. seealso::

   :doc:`/howto/protocols`
      Explains what a :class:`.DatagramProtocol` is and how to use it.


Connecting To Peer
==================

.. important::

   If you are familiar with UDP sockets, you know that there are no real connections (communication pipes) like there are with TCP sockets.

   If not, I advise you to read the Unix manual pages :manpage:`udp(7)` and :manpage:`connect(2)`.

You need the listening socket's filepath:

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/basics/api_sync/connection_example1.py
         :linenos:

      .. note::

         The client does nothing when it enters the :keyword:`with` context. Everything is done on object creation.

   .. group-tab:: Asynchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/basics/api_async/connection_example1.py
         :linenos:

      .. note::

         The call to :meth:`~.AsyncUnixDatagramClient.wait_connected` is required to actually initialize the client,
         since we cannot perform asynchronous operations at object creation.
         This is what the client does when it enters the the :keyword:`async with` context.

         Once completed, :meth:`~.AsyncUnixDatagramClient.wait_connected` is a no-op.


Using An Already Connected Socket
=================================

If you have your own way to obtain a connected :class:`socket.socket` instance, you can pass it to the client.

If the socket is not connected, an :exc:`OSError` is raised.

.. important::

   It *must* be a :data:`~socket.SOCK_DGRAM` socket with :data:`~socket.AF_UNIX` family.

.. warning::

   The resource ownership is given to the client. You must close the client to close the socket.

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/basics/api_sync/socket_example1.py
         :linenos:

   .. group-tab:: Asynchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/basics/api_async/socket_example1.py
         :linenos:

      .. note::

         Even with a ready-to-use socket, the call to :meth:`~.AsyncUnixDatagramClient.wait_connected` is still required.


Sending Packets
===============

There's not much to say, except that objects passed as arguments are automatically converted to bytes to send to the remote host
thanks to the :term:`protocol object`.

.. warning::

   Sending socket control messages ( with :manpage:`sendmsg(2)` ) is not supported yet.

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/usage/api_sync.py
         :pyobject: send_packet_example1
         :start-after: [start]
         :dedent:
         :linenos:

   .. group-tab:: Asynchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/usage/api_async.py
         :pyobject: send_packet_example1
         :start-after: [start]
         :dedent:
         :linenos:


Receiving Packets
=================

You get the next available packet, already parsed.

.. warning::

   Receiving socket control messages ( with :manpage:`recvmsg(2)` ) is not supported yet.

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/usage/api_sync.py
         :pyobject: recv_packet_example1
         :start-after: [start]
         :dedent:
         :linenos:

      You can control the receive timeout with the ``timeout`` parameter:

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/usage/api_sync.py
         :pyobject: recv_packet_example2
         :start-after: [start]
         :dedent:
         :linenos:

   .. group-tab:: Asynchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/usage/api_async.py
         :pyobject: recv_packet_example1
         :start-after: [start]
         :dedent:
         :linenos:

      You can control the receive timeout by adding a timeout scope using the :term:`asynchronous framework` :

      .. tabs::

         .. group-tab:: Using ``asyncio``

            .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/usage/api_async.py
               :pyobject: recv_packet_example2_asyncio
               :start-after: [start]
               :dedent:
               :linenos:

         .. group-tab:: Using ``trio``

            .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/usage/api_async.py
               :pyobject: recv_packet_example2_trio
               :start-after: [start]
               :dedent:
               :linenos:

         .. group-tab:: Using the ``AsyncBackend`` API

            .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/usage/api_async.py
               :pyobject: recv_packet_example2_backend_api
               :start-after: [start]
               :dedent:
               :linenos:


.. tip::

   Remember to catch invalid data parsing errors.

   .. tabs::

      .. group-tab:: Synchronous

         .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/usage/api_sync.py
            :pyobject: recv_packet_example3
            :start-after: [start]
            :dedent:
            :linenos:
            :emphasize-lines: 3-4

      .. group-tab:: Asynchronous

         .. tabs::

            .. group-tab:: Using ``asyncio``

               .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/usage/api_async.py
                  :pyobject: recv_packet_example3_asyncio
                  :start-after: [start]
                  :dedent:
                  :linenos:
                  :emphasize-lines: 4-5

            .. group-tab:: Using ``trio``

               .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/usage/api_async.py
                  :pyobject: recv_packet_example3_trio
                  :start-after: [start]
                  :dedent:
                  :linenos:
                  :emphasize-lines: 4-5

            .. group-tab:: Using the ``AsyncBackend`` API

               .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/usage/api_async.py
                  :pyobject: recv_packet_example3_backend_api
                  :start-after: [start]
                  :dedent:
                  :linenos:
                  :emphasize-lines: 4-5


Receiving Multiple Packets At Once
==================================

You can use ``iter_received_packets()`` to get all the received packets in a sequence or a set.

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/usage/api_sync.py
         :pyobject: recv_packet_example4
         :start-after: [start]
         :dedent:
         :linenos:

   .. group-tab:: Asynchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/usage/api_async.py
         :pyobject: recv_packet_example4
         :start-after: [start]
         :dedent:
         :linenos:

The ``timeout`` parameter defaults to zero to get only the data already in the buffer, but you can change it.

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/usage/api_sync.py
         :pyobject: recv_packet_example5
         :start-after: [start]
         :dedent:
         :linenos:

      .. seealso::

         :meth:`.UnixDatagramClient.iter_received_packets`
            The method description and usage (especially for the ``timeout`` parameter).

   .. group-tab:: Asynchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/usage/api_async.py
         :pyobject: recv_packet_example5
         :start-after: [start]
         :dedent:
         :linenos:

      .. seealso::

         :meth:`.AsyncUnixDatagramClient.iter_received_packets`
            The method description and usage (especially for the ``timeout`` parameter).


Low-Level Socket Operations
===========================

For low-level operations such as :meth:`~socket.socket.setsockopt`, the client object exposes the socket through a :class:`.SocketProxy`:

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/usage/api_sync.py
         :pyobject: socket_proxy_example
         :start-after: [start]
         :dedent:
         :linenos:

   .. group-tab:: Asynchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_clients/usage/api_async.py
         :pyobject: socket_proxy_example
         :start-after: [start]
         :dedent:
         :linenos:

      .. warning::

         Make sure that :meth:`~.AsyncUnixDatagramClient.wait_connected` has been called before.


Concurrency And Multithreading
==============================

.. tabs::

   .. group-tab:: Synchronous

      All client methods are thread-safe. Synchronization follows these rules:

      * :meth:`~.UnixDatagramClient.send_packet` and :meth:`~.UnixDatagramClient.recv_packet` do not share the same
        :class:`threading.Lock` instance.

      * :meth:`~.UnixDatagramClient.close` will not wait for :meth:`~.UnixDatagramClient.recv_packet`.

      * The :attr:`client.socket <.UnixDatagramClient.socket>` methods are also thread-safe. This means that you cannot access
        the underlying socket methods (e.g. :meth:`~socket.socket.getsockopt`) during a write operation.

   .. group-tab:: Asynchronous

      All client methods do not require external task synchronization (such as :class:`asyncio.Lock`).
      Synchronization follows these rules:

      * :meth:`~.AsyncUnixDatagramClient.send_packet` and :meth:`~.AsyncUnixDatagramClient.recv_packet` do not share the same lock instance.

      * :meth:`~.AsyncUnixDatagramClient.aclose` will not wait for :meth:`~.AsyncUnixDatagramClient.recv_packet`.
