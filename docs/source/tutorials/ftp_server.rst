********************************************************
Practical application — Build an FTP server from scratch
********************************************************

.. include:: ../_include/sync-async-variants.rst

.. contents:: Table of Contents
   :local:


------


TL;DR
=====

Yes, I know, you will never need to create your own FTP server (unless you want your own service). However, it is still interesting
to see the structure of such a model, based on a standardized communication protocol.

The `File Transfer Protocol`_ (as defined in :rfc:`959`) is a good example of how to set up a server with precise rules.

We are not going to implement all the requests (that is not the point). The tutorial will show you how to set up the infrastructure
and exploit all (or most) of the EasyNetwork library's features.


The Communication Protocol
==========================

FTP requests and responses are transmitted as ASCII strings separated by a carriage return (``\r\n``).

Let's say we want to have two classes ``FTPRequest`` and ``FTPReply`` to manage them in our request handler.

``FTPRequest`` Object
---------------------

An FTP client request consists of a command and, optionally, arguments separated by a space character.

First, we define the exhaustive list of available commands (c.f. :rfc:`RFC 959 (Section 4.1) <959#section-4>`):

.. literalinclude:: ../_include/examples/tutorials/ftp_server/ftp_command.py
   :linenos:
   :caption: ftp_command.py

.. note::

   See :mod:`enum` module documentation to understand the usage of :class:`~enum.auto` and :meth:`~enum.Enum._generate_next_value_`.

Second, we define the ``FTPRequest`` class that will be used:

.. literalinclude:: ../_include/examples/tutorials/ftp_server/ftp_request.py
   :linenos:
   :caption: ftp_request.py


``FTPReply`` Object
-------------------

An FTP reply consists of a three-digit number (transmitted as three alphanumeric characters) followed by some text.

.. literalinclude:: ../_include/examples/tutorials/ftp_server/ftp_reply.py
   :linenos:
   :caption: ftp_reply.py
   :end-before: @staticmethod


Use Converters To Handle Character Strings
------------------------------------------

The client will send a character string and expect a character string in return. :class:`.StringLineSerializer` will handle this part,
but we have created our objects in order not to manipulate strings.

To remedy this, we will use :term:`converters <converter>` to switch between our ``FTPRequest`` / ``FTPReply`` objects and strings.

.. literalinclude:: ../_include/examples/tutorials/ftp_server/ftp_converters.py
   :linenos:
   :caption: ftp_converters.py

.. note::

   In :meth:`FTPRequestConverter.create_from_dto_packet`, the arguments are left as sent and returned.

   .. literalinclude:: ../_include/examples/tutorials/ftp_server/ftp_converters.py
      :pyobject: FTPRequestConverter.create_from_dto_packet
      :start-at: try:
      :end-at: return FTPRequest
      :lineno-match:
      :emphasize-lines: 5
      :dedent:

   An improvement would be to process them here and not leave the job to the request handler.
   But since we are not building a real (complete and fully featured) FTP server, we will leave the code as is.

The Protocol Object
-------------------

Now that we have our business objects, we can create our :term:`protocol object`.

.. literalinclude:: ../_include/examples/tutorials/ftp_server/ftp_server_protocol.py
   :linenos:
   :caption: ftp_server_protocol.py


.. note::

   Note the use of :class:`.StapledPacketConverter`:

   .. literalinclude:: ../_include/examples/tutorials/ftp_server/ftp_server_protocol.py
      :pyobject: FTPServerProtocol.__init__
      :start-at: super().__init__
      :lineno-match:
      :emphasize-lines: 3-6
      :dedent:

   It will create a :term:`composite converter` with our two converters.


The Server
==========

``FTPReply``: Define Default Replies
------------------------------------

A good way to reply to the client with default replies is to define them in methods.

Here are just a few that will be used in this tutorial.

.. literalinclude:: ../_include/examples/tutorials/ftp_server/ftp_reply.py
   :caption: ftp_reply.py
   :pyobject: FTPReply
   :lineno-match:


The Request Handler
-------------------

Let's create this request handler.

Service Initialization
^^^^^^^^^^^^^^^^^^^^^^

A feature we could have used for the :ref:`echo client/server over TCP tutorial <echo-client-server-tcp-request-handler>`
is to define actions to perform at start/end of the server.

Here, we'll only initialize the logger, but we could also use it to prepare the folders and files that the server should handle
(location, permissions, file existence, etc.).

.. literalinclude:: ../_include/examples/tutorials/ftp_server/ftp_server_request_handler.py
   :pyobject: FTPRequestHandler
   :end-before: async def on_connection
   :lineno-match:
   :dedent:


Control Connection Hooks
^^^^^^^^^^^^^^^^^^^^^^^^

Here are the features brought by :class:`.AsyncStreamRequestHandler`: It is possible to perform actions when connecting/disconnecting the client.

.. literalinclude:: ../_include/examples/tutorials/ftp_server/ftp_server_request_handler.py
   :pyobject: FTPRequestHandler
   :start-at: async def on_connection
   :end-before: async def handle
   :lineno-match:
   :dedent:


The :meth:`~handle` Method
^^^^^^^^^^^^^^^^^^^^^^^^^^

Only ``NOOP`` and ``QUIT`` commands will be implemented for this tutorial. All parse errors are considered syntax errors.

.. literalinclude:: ../_include/examples/tutorials/ftp_server/ftp_server_request_handler.py
   :pyobject: FTPRequestHandler.handle
   :lineno-match:
   :dedent:


Full Code
^^^^^^^^^

.. literalinclude:: ../_include/examples/tutorials/ftp_server/ftp_server_request_handler.py
   :caption: ftp_server_request_handler.py
   :linenos:


Start The Server
----------------

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../_include/examples/tutorials/ftp_server/server.py
         :linenos:
         :caption: server.py

   .. group-tab:: Asynchronous (asyncio)

      .. literalinclude:: ../_include/examples/tutorials/ftp_server/async_server_asyncio.py
         :linenos:
         :caption: server.py

   .. group-tab:: Asynchronous (trio)

      .. literalinclude:: ../_include/examples/tutorials/ftp_server/async_server_trio.py
         :linenos:
         :caption: server.py


Outputs
=======

The output of the example should look something like this:

Server:

.. tabs::

   .. group-tab:: IPv4 connection

      .. code-block:: console

         (.venv) $ python server.py
         [ INFO ] [ easynetwork.servers.async_tcp ] Start serving at ('::', 21000), ('0.0.0.0', 21000)
         [ INFO ] [ easynetwork.servers.async_tcp ] Accepted new connection (address = ('127.0.0.1', 45994))
         [ INFO ] [ FTPRequestHandler ] Sent by client ('127.0.0.1', 45994): FTPRequest(command=<FTPCommand.NOOP: 'NOOP'>, args=())
         [ INFO ] [ FTPRequestHandler ] Sent by client ('127.0.0.1', 45994): FTPRequest(command=<FTPCommand.NOOP: 'NOOP'>, args=())
         [ INFO ] [ FTPRequestHandler ] Sent by client ('127.0.0.1', 45994): FTPRequest(command=<FTPCommand.STOR: 'STOR'>, args=('/path/to/file.txt',))
         [ WARNING ] [ FTPRequestHandler ] ('127.0.0.1', 45994): PacketConversionError: Command unrecognized: 'UNKNOWN'
         [ INFO ] [ FTPRequestHandler ] Sent by client ('127.0.0.1', 45994): FTPRequest(command=<FTPCommand.QUIT: 'QUIT'>, args=())
         [ INFO ] [ easynetwork.servers.async_tcp ] ('127.0.0.1', 45994) disconnected

   .. group-tab:: IPv6 connection

      .. code-block:: console

         (.venv) $ python server.py
         [ INFO ] [ easynetwork.servers.async_tcp ] Start serving at ('::', 21000), ('0.0.0.0', 21000)
         [ INFO ] [ easynetwork.servers.async_tcp ] Accepted new connection (address = ('::1', 45994))
         [ INFO ] [ FTPRequestHandler ] Sent by client ('::1', 45994): FTPRequest(command=<FTPCommand.NOOP: 'NOOP'>, args=())
         [ INFO ] [ FTPRequestHandler ] Sent by client ('::1', 45994): FTPRequest(command=<FTPCommand.NOOP: 'NOOP'>, args=())
         [ INFO ] [ FTPRequestHandler ] Sent by client ('::1', 45994): FTPRequest(command=<FTPCommand.STOR: 'STOR'>, args=('/path/to/file.txt',))
         [ WARNING ] [ FTPRequestHandler ] ('::1', 45994): PacketConversionError: Command unrecognized: 'UNKNOWN'
         [ INFO ] [ FTPRequestHandler ] Sent by client ('::1', 45994): FTPRequest(command=<FTPCommand.QUIT: 'QUIT'>, args=())
         [ INFO ] [ easynetwork.servers.async_tcp ] ('::1', 45994) disconnected


Client:

.. note::

   The `File Transfer Protocol`_ is based on the `Telnet protocol`_.

   The :manpage:`telnet(1)` command is used to communicate with another host using the `Telnet protocol`_.

.. tabs::

   .. group-tab:: IPv4 connection

      .. code-block:: console

         $ telnet -4 localhost 21000
         Trying 127.0.0.1...
         Connected to localhost.
         Escape character is '^]'.
         220 Service ready for new user.
         NOOP
         200 Command okay.
         nOoP
         200 Command okay.
         STOR /path/to/file.txt
         502 Command not implemented.
         UNKNOWN command
         500 Syntax error, command unrecognized.
         QUIT
         221 Service closing control connection.
         Connection closed by foreign host.

   .. group-tab:: IPv6 connection

      .. code-block:: console

         $ telnet -6 localhost 21000
         Trying ::1...
         Connected to localhost.
         Escape character is '^]'.
         220 Service ready for new user.
         NOOP
         200 Command okay.
         nOoP
         200 Command okay.
         STOR /path/to/file.txt
         502 Command not implemented.
         UNKNOWN command
         500 Syntax error, command unrecognized.
         QUIT
         221 Service closing control connection.
         Connection closed by foreign host.


.. Links

.. include:: ../_include/link-labels.rst
