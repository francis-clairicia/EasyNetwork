******************************
An Echo Client/Server Over UDP
******************************

It is possible to do the same as :doc:`the TCP server tutorial <./echo_client_server_tcp>` with UDP sockets.

.. include:: ../_include/sync-async-variants.rst

.. contents:: Table of Contents
   :local:


------


The Communication Protocol
==========================

You will need a :term:`protocol object`, as for the :ref:`echo client/server over TCP <echo-client-server-tcp-protocol>`.

For the tutorial, :class:`.JSONSerializer` will also be used.

For communication via UDP, a :class:`.DatagramProtocol` object must be created this time.

.. literalinclude:: ../_include/examples/tutorials/echo_client_server_udp/json_protocol.py
   :linenos:
   :caption: json_protocol.py
   :emphasize-lines: 5,14


The Server
==========

Create Your Datagram Request Handler
------------------------------------

First, you must create a request handler class by subclassing the :class:`.AsyncDatagramRequestHandler` class and overriding
its :meth:`~.AsyncDatagramRequestHandler.handle` method; this method will process incoming requests.

.. literalinclude:: ../_include/examples/tutorials/echo_client_server_udp/echo_request_handler.py
   :linenos:
   :caption: echo_request_handler.py
   :emphasize-lines: 13,16,20

.. note::

   There is no connection pipe with UDP, so there is no ``aclose()`` method.
   But the client object still has an ``is_closing()`` that returns :data:`True` when the server itself closes.


Start The Server
----------------

Second, you must instantiate the UDP server class, passing it the server's address, the :term:`protocol object` instance,
and the request handler instance.

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../_include/examples/tutorials/echo_client_server_udp/server.py
         :linenos:
         :caption: server.py

   .. group-tab:: Asynchronous (asyncio)

      .. literalinclude:: ../_include/examples/tutorials/echo_client_server_udp/async_server_asyncio.py
         :linenos:
         :caption: server.py

   .. group-tab:: Asynchronous (trio)

      .. literalinclude:: ../_include/examples/tutorials/echo_client_server_udp/async_server_trio.py
         :linenos:
         :caption: server.py


The Client
==========

This is the client side:

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../_include/examples/tutorials/echo_client_server_udp/client.py
         :linenos:
         :caption: client.py

   .. group-tab:: Asynchronous (asyncio)

      .. literalinclude:: ../_include/examples/tutorials/echo_client_server_udp/async_client_asyncio.py
         :linenos:
         :caption: client.py

   .. group-tab:: Asynchronous (trio)

      .. literalinclude:: ../_include/examples/tutorials/echo_client_server_udp/async_client_trio.py
         :linenos:
         :caption: client.py

.. note::

   This is a "spoofed" connection. In fact, the socket is saving the address and will only send data to that endpoint.


Outputs
=======

The output of the example should look something like this:

Server:

.. tabs::

   .. group-tab:: IPv4 connection

      .. code-block:: console

         (.venv) $ python server.py
         127.0.0.1 sent {'command-line arguments': ['Hello', 'world!']}
         127.0.0.1 sent {'command-line arguments': ['Python', 'is', 'nice']}

   .. group-tab:: IPv6 connection

      .. code-block:: console

         (.venv) $ python server.py
         ::1 sent {'command-line arguments': ['Hello', 'world!']}
         ::1 sent {'command-line arguments': ['Python', 'is', 'nice']}

Client:

.. code-block:: console

   (.venv) $ python client.py Hello world!
   Sent:     {'command-line arguments': ['Hello', 'world!']}
   Received: {'command-line arguments': ['Hello', 'world!']}
   (.venv) $ python client.py Python is nice
   Sent:     {'command-line arguments': ['Python', 'is', 'nice']}
   Received: {'command-line arguments': ['Python', 'is', 'nice']}


.. include:: ../_include/link-labels.rst
