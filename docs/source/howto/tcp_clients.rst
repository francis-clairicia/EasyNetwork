*****************************
How-to — TCP Client Endpoints
*****************************

.. include:: ../_include/sync-async-variants.rst

.. contents:: Table of Contents
   :local:

------

The Protocol Object
===================

The TCP clients expect a :class:`.StreamProtocol` instance to communicate with the remote endpoint.

.. seealso::

   :doc:`protocols`
      Explains what a :class:`.StreamProtocol` is and how to use it.


Connecting To The Remote Host
=============================

You need the host address (domain name or IP) and the port of connection in order to connect to the remote host:

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../_include/examples/howto/tcp_clients/basics/api_sync/connection_example1.py
         :linenos:

      You can control the connection timeout with the ``connect_timeout`` parameter:

      .. literalinclude:: ../_include/examples/howto/tcp_clients/basics/api_sync/connection_example2.py
         :pyobject: main
         :lineno-match:
         :emphasize-lines: 5-11

      .. note::

         The client does nothing when it enters the :keyword:`with` context. Everything is done on object creation.

   .. group-tab:: Asynchronous

      .. literalinclude:: ../_include/examples/howto/tcp_clients/basics/api_async/connection_example1.py
         :linenos:

      You can control the connection timeout by adding a timeout scope using the :term:`asynchronous framework`:

      .. tabs::

         .. group-tab:: Using ``asyncio``

            .. literalinclude:: ../_include/examples/howto/tcp_clients/basics/api_async/connection_example2_asyncio.py
               :pyobject: main
               :lineno-match:
               :emphasize-lines: 5-13

         .. group-tab:: Using ``trio``

            .. literalinclude:: ../_include/examples/howto/tcp_clients/basics/api_async/connection_example2_trio.py
               :pyobject: main
               :lineno-match:
               :emphasize-lines: 5-13

         .. group-tab:: Using the ``AsyncBackend`` API

            .. literalinclude:: ../_include/examples/howto/tcp_clients/basics/api_async/connection_example2_backend_api.py
               :pyobject: main
               :lineno-match:
               :emphasize-lines: 5-13

      .. note::

         The call to :meth:`~.AsyncTCPNetworkClient.wait_connected` is required to actually initialize the client,
         since we cannot perform asynchronous operations at object creation.
         This is what the client does when it enters the the :keyword:`async with` context.

         Once completed, :meth:`~.AsyncTCPNetworkClient.wait_connected` is a no-op.


Using An Already Connected Socket
=================================

If you have your own way to obtain a connected :class:`socket.socket` instance, you can pass it to the client.

If the socket is not connected, an :exc:`OSError` is raised.

.. important::

   It *must* be a :data:`~socket.SOCK_STREAM` socket with :data:`~socket.AF_INET` or :data:`~socket.AF_INET6` family.

.. warning::

   The resource ownership is given to the client. You must close the client to close the socket.

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../_include/examples/howto/tcp_clients/basics/api_sync/socket_example1.py
         :linenos:

   .. group-tab:: Asynchronous

      .. literalinclude:: ../_include/examples/howto/tcp_clients/basics/api_async/socket_example1.py
         :linenos:

      .. note::

         Even with a ready-to-use socket, the call to :meth:`~.AsyncTCPNetworkClient.wait_connected` is still required.


Sending Packets
===============

There's not much to say, except that objects passed as arguments are automatically converted to bytes to send to the remote host
thanks to the :term:`protocol object`.

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_sync.py
         :pyobject: send_packet_example1
         :start-after: [start]
         :dedent:
         :linenos:

   .. group-tab:: Asynchronous

      .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_async.py
         :pyobject: send_packet_example1
         :start-after: [start]
         :dedent:
         :linenos:


Receiving Packets
=================

You get the next available packet, already parsed. Extraneous data is kept for the next call.

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_sync.py
         :pyobject: recv_packet_example1
         :start-after: [start]
         :dedent:
         :linenos:

      You can control the receive timeout with the ``timeout`` parameter:

      .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_sync.py
         :pyobject: recv_packet_example2
         :start-after: [start]
         :dedent:
         :linenos:

   .. group-tab:: Asynchronous

      .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_async.py
         :pyobject: recv_packet_example1
         :start-after: [start]
         :dedent:
         :linenos:

      You can control the receive timeout by adding a timeout scope using the :term:`asynchronous framework`:

      .. tabs::

         .. group-tab:: Using ``asyncio``

            .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_async.py
               :pyobject: recv_packet_example2_asyncio
               :start-after: [start]
               :dedent:
               :linenos:

         .. group-tab:: Using ``trio``

            .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_async.py
               :pyobject: recv_packet_example2_trio
               :start-after: [start]
               :dedent:
               :linenos:

         .. group-tab:: Using the ``AsyncBackend`` API

            .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_async.py
               :pyobject: recv_packet_example2_backend_api
               :start-after: [start]
               :dedent:
               :linenos:


.. tip::

   Remember to catch invalid data parsing errors.

   .. tabs::

      .. group-tab:: Synchronous

         .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_sync.py
            :pyobject: recv_packet_example3
            :start-after: [start]
            :dedent:
            :linenos:
            :emphasize-lines: 3-4

      .. group-tab:: Asynchronous

         .. tabs::

            .. group-tab:: Using ``asyncio``

               .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_async.py
                  :pyobject: recv_packet_example3_asyncio
                  :start-after: [start]
                  :dedent:
                  :linenos:
                  :emphasize-lines: 4-5

            .. group-tab:: Using ``trio``

               .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_async.py
                  :pyobject: recv_packet_example3_trio
                  :start-after: [start]
                  :dedent:
                  :linenos:
                  :emphasize-lines: 4-5

            .. group-tab:: Using the ``AsyncBackend`` API

               .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_async.py
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

      .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_sync.py
         :pyobject: recv_packet_example4
         :start-after: [start]
         :dedent:
         :linenos:

   .. group-tab:: Asynchronous

      .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_async.py
         :pyobject: recv_packet_example4
         :start-after: [start]
         :dedent:
         :linenos:

The ``timeout`` parameter defaults to zero to get only the data already in the buffer, but you can change it.

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_sync.py
         :pyobject: recv_packet_example5
         :start-after: [start]
         :dedent:
         :linenos:

      .. seealso::

         :meth:`.TCPNetworkClient.iter_received_packets`
            The method description and usage (especially for the ``timeout`` parameter).

   .. group-tab:: Asynchronous

      .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_async.py
         :pyobject: recv_packet_example5
         :start-after: [start]
         :dedent:
         :linenos:

      .. seealso::

         :meth:`.AsyncTCPNetworkClient.iter_received_packets`
            The method description and usage (especially for the ``timeout`` parameter).


Close The Write-End Stream
==========================

If you are sure you will never reuse ``send_packet()``, you can call ``send_eof()`` to shut down the write stream.

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_sync.py
         :pyobject: send_eof_example
         :start-after: [start]
         :dedent:
         :linenos:

   .. group-tab:: Asynchronous

      .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_async.py
         :pyobject: send_eof_example
         :start-after: [start]
         :dedent:
         :linenos:

.. note::

   ``send_eof()`` will block until all unsent data has been flushed before closing the stream.


Low-Level Socket Operations
===========================

For low-level operations such as :meth:`~socket.socket.setsockopt`, the client object exposes the socket through a :class:`.SocketProxy`:

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_sync.py
         :pyobject: socket_proxy_example
         :start-after: [start]
         :dedent:
         :linenos:

   .. group-tab:: Asynchronous

      .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_async.py
         :pyobject: socket_proxy_example
         :start-after: [start]
         :dedent:
         :linenos:

      .. warning::

         Make sure that :meth:`~.AsyncTCPNetworkClient.wait_connected` has been called before.


``socket.recv()`` Buffer Size
=============================

By default, the client uses a reasonable buffer size when calling ``recv_packet()``.
You can control this value by setting the ``max_recv_size`` parameter:

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_sync.py
         :pyobject: max_recv_size_example
         :start-after: [start]
         :dedent:
         :linenos:

   .. group-tab:: Asynchronous

      .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_async.py
         :pyobject: max_recv_size_example
         :start-after: [start]
         :dedent:
         :linenos:


.. note::

   ``max_recv_size`` is also used as a size hint for :term:`buffered serializers <buffered serializer>`.
   See :ref:`this section <buffer-instantiation>` for details.


SSL/TLS Connection
==================

If you want to use SSL to communicate with the remote host, the easiest way is to pass ``ssl=True``:

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_sync.py
         :pyobject: ssl_default_context_example
         :start-after: [start]
         :dedent:
         :linenos:

   .. group-tab:: Asynchronous

      .. literalinclude:: ../_include/examples/howto/tcp_clients/usage/api_async.py
         :pyobject: ssl_default_context_example
         :start-after: [start]
         :dedent:
         :linenos:

.. note::

   Since this is a *client* object, :meth:`ssl.SSLContext.wrap_socket` and :meth:`ssl.SSLContext.wrap_bio` are always called
   with ``server_side=False``.

.. danger::

   You can pass an :class:`~ssl.SSLContext` instead, but at this point I expect you to *really* know what you are doing.


Concurrency And Multithreading
==============================

.. tabs::

   .. group-tab:: Synchronous

      All client methods are thread-safe. Synchronization follows these rules:

      * :meth:`~.TCPNetworkClient.send_packet` and :meth:`~.TCPNetworkClient.recv_packet` do not share the same
        :class:`threading.Lock` instance.

      * :meth:`~.TCPNetworkClient.close` will not wait for :meth:`~.TCPNetworkClient.recv_packet`.

      * The :attr:`client.socket <.TCPNetworkClient.socket>` methods are also thread-safe. This means that you cannot access
        the underlying socket methods (e.g. :meth:`~socket.socket.getsockopt`) during a write operation.

   .. group-tab:: Asynchronous

      All client methods do not require external task synchronization (such as :class:`asyncio.Lock`).
      Synchronization follows these rules:

      * :meth:`~.AsyncTCPNetworkClient.send_packet` and :meth:`~.AsyncTCPNetworkClient.recv_packet` do not share the same lock instance.

      * :meth:`~.AsyncTCPNetworkClient.aclose` will not wait for :meth:`~.AsyncTCPNetworkClient.recv_packet`.
