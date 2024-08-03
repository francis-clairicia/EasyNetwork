******************************
An Echo Client/Server Over TCP
******************************

To see how to create a server and a client with the minimum requirements,
let's create a server that will return everything sent by a connected client.

.. include:: ../_include/sync-async-variants.rst

.. contents:: Table of Contents
   :local:


------


.. _echo-client-server-tcp-protocol:

The Communication Protocol
==========================

Before doing all this networking stuff, you need to know what you want to transmit and in what format. It is your :term:`communication protocol`.

Choose The Serializer
---------------------

There is a bunch of serializers available in :mod:`easynetwork.serializers` for everyone to enjoy:

* :class:`.JSONSerializer`: an :term:`incremental serializer` using the :mod:`json` module.

* :class:`.PickleSerializer`: a :term:`one-shot serializer` using the :mod:`pickle` module.

* :class:`.StringLineSerializer`: an :term:`incremental serializer` for communication based on ASCII character strings (e.g. `FTP`_).

* etc.

For the tutorial, :class:`.JSONSerializer` will be used.


Build Your Protocol Object
--------------------------

For communication via TCP, a :class:`.StreamProtocol` :term:`protocol object` must be created.

.. literalinclude:: ../_include/examples/tutorials/echo_client_server_tcp/json_protocol.py
   :linenos:
   :caption: json_protocol.py

.. note::

   Of course, you are under no obligation to write a subclass. But see :ref:`this note <why-write-a-protocol-subclass>` for details.


The Server
==========

Now that we have established the :term:`communication protocol`, we can create our server.

.. _echo-client-server-tcp-request-handler:

Create Your Request Handler
---------------------------

First, you must create a request handler class by subclassing the :class:`.AsyncStreamRequestHandler` class and overriding
its :meth:`~.AsyncStreamRequestHandler.handle` method; this method will process incoming requests.

.. literalinclude:: ../_include/examples/tutorials/echo_client_server_tcp/echo_request_handler.py
   :linenos:
   :caption: echo_request_handler.py

.. note::

   Pay attention to :meth:`~.AsyncStreamRequestHandler.handle`, it is an :std:term:`asynchronous generator` function.
   All requests sent by the client are literally injected into the generator via the :keyword:`yield` statement.

   .. literalinclude:: ../_include/examples/tutorials/echo_client_server_tcp/echo_request_handler.py
      :start-at: async def handle
      :end-at: return
      :lineno-match:
      :emphasize-lines: 6
      :dedent:

   You can :keyword:`yield` several times if you want to wait for a new packet from the client in the same context.

.. warning::

   Leaving the generator will *not* close the connection, a new generator will be created afterwards.
   You may, however, explicitly close the connection if you want to::

      await client.aclose()


Start The Server
----------------

Second, you must instantiate the TCP server class, passing it the server's address, the :term:`protocol object` instance,
and the request handler instance.

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../_include/examples/tutorials/echo_client_server_tcp/server.py
         :linenos:
         :caption: server.py

   .. group-tab:: Asynchronous (asyncio)

      .. literalinclude:: ../_include/examples/tutorials/echo_client_server_tcp/async_server_asyncio.py
         :linenos:
         :caption: server.py

   .. group-tab:: Asynchronous (trio)

      .. literalinclude:: ../_include/examples/tutorials/echo_client_server_tcp/async_server_trio.py
         :linenos:
         :caption: server.py

.. note::

   Setting ``host`` to :data:`None` will bind the server to all interfaces.
   This means the server is ready to accept connections with IPv4 and IPv6 addresses (if available).


The Client
==========

This is the client side:

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../_include/examples/tutorials/echo_client_server_tcp/client.py
         :linenos:
         :caption: client.py

   .. group-tab:: Asynchronous (asyncio)

      .. literalinclude:: ../_include/examples/tutorials/echo_client_server_tcp/async_client_asyncio.py
         :linenos:
         :caption: client.py

   .. group-tab:: Asynchronous (trio)

      .. literalinclude:: ../_include/examples/tutorials/echo_client_server_tcp/async_client_trio.py
         :linenos:
         :caption: client.py


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
