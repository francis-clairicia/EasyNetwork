***********************************
Alternative — Unix Datagram Servers
***********************************

.. include:: ../../_include/sync-async-variants.rst

.. contents:: Table of Contents
   :local:

------

Introduction
============

Creating a Unix datagram server requires several steps:

.. tabs::

   .. group-tab:: Synchronous

      #. Derive a class from :class:`.BlockingDatagramRequestHandler` and redefine its :meth:`~.BlockingDatagramRequestHandler.handle` method;
         this method will process incoming requests.

      #. Instantiate the :class:`.ThreadedUnixDatagramServer` class passing it the server's address, the :term:`protocol object`
         and the request handler instance.

      #. Call :meth:`~.ThreadedUnixDatagramServer.serve_forever` to process requests.

   .. group-tab:: Asynchronous

      #. Derive a class from :class:`.AsyncDatagramRequestHandler` and redefine its :meth:`~.AsyncDatagramRequestHandler.handle` method;
         this method will process incoming requests.

      #. Instantiate the :class:`.AsyncUnixDatagramServer` class passing it the server's address, the :term:`protocol object`
         and the request handler instance.

      #. Call :meth:`~.AsyncUnixDatagramServer.serve_forever` to process requests.

      .. seealso::

         :pep:`492` — Coroutines with async and await syntax
            The proposal to introduce native coroutines in Python with :keyword:`async` and :keyword:`await` syntax.

         :external+python:doc:`library/asyncio`
            If you are not familiar with async/await syntax, you can use the standard library to get started with coroutines.


Request Handler Objects
=======================

.. note::

   Unlike :class:`socketserver.BaseRequestHandler`, there is **only one** request handler instance for the entire service.


Here is a simple example:

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/blocking_simple_request_handler.py
         :linenos:

   .. group-tab:: Asynchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_simple_request_handler.py
         :linenos:


Using ``handle()`` Generator
----------------------------

.. important::
   There will always be only one active generator per client.
   All the pending datagrams received while the generator is running are queued.

   This behavior is designed to act like a stream request handler.


Minimum Requirements
^^^^^^^^^^^^^^^^^^^^

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/blocking_request_handler_explanation.py
         :pyobject: MinimumRequestHandler.handle
         :dedent:
         :linenos:

   .. group-tab:: Asynchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_request_handler_explanation.py
         :pyobject: MinimumRequestHandler.handle
         :dedent:
         :linenos:


Refuse datagrams
^^^^^^^^^^^^^^^^

Your UDP socket can receive datagrams from anyone with permission to send them. You may want to control who can send you information.

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/blocking_request_handler_explanation.py
         :pyobject: SkipDatagramRequestHandler.handle
         :dedent:
         :linenos:
         :emphasize-lines: 5-8

   .. group-tab:: Asynchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_request_handler_explanation.py
         :pyobject: SkipDatagramRequestHandler.handle
         :dedent:
         :linenos:
         :emphasize-lines: 5-8

Error Handling
^^^^^^^^^^^^^^

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/blocking_request_handler_explanation.py
         :pyobject: ErrorHandlingInRequestHandler.handle
         :dedent:
         :linenos:

   .. group-tab:: Asynchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_request_handler_explanation.py
         :pyobject: ErrorHandlingInRequestHandler.handle
         :dedent:
         :linenos:

.. warning::

   You should always log or re-raise a bare :exc:`Exception` thrown in your generator.

   .. tabs::

      .. group-tab:: Synchronous

         .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/blocking_request_handler_explanation.py
            :pyobject: ErrorHandlingInRequestHandler.handle
            :dedent:
            :linenos:
            :start-at: except Exception
            :end-at: InternalError()
            :emphasize-lines: 2-3

      .. group-tab:: Asynchronous

         .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_request_handler_explanation.py
            :pyobject: ErrorHandlingInRequestHandler.handle
            :dedent:
            :linenos:
            :start-at: except Exception
            :end-at: InternalError()
            :emphasize-lines: 2-3


Having Multiple ``yield`` Statements
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/blocking_request_handler_explanation.py
         :pyobject: MultipleYieldInRequestHandler.handle
         :dedent:
         :linenos:
         :emphasize-lines: 5,12

   .. group-tab:: Asynchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_request_handler_explanation.py
         :pyobject: MultipleYieldInRequestHandler.handle
         :dedent:
         :linenos:
         :emphasize-lines: 5,12

.. warning::

   Even if this feature is supported, it is not recommended to have more than one (unless you know what you are doing) for the following reasons:

   * UDP does not guarantee ordered delivery. Packets are typically "sent" in order, but they may be received out of order.
     In large networks, it is reasonably common for some packets to arrive out of sequence (or not at all).

   * The server has no way of knowing if this client has stopped sending you requests forever.

   If you plan to use multiple yields in your request handler, you should *always* have a timeout applied. (See the section below.)


Cancellation And Timeouts
^^^^^^^^^^^^^^^^^^^^^^^^^

.. tabs::

   .. tab:: Using ``yield`` (Recommended)

      It is possible to send the timeout delay to the parent task by using :class:`.RecvParams`:

      .. tabs::

         .. group-tab:: Synchronous

            .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/blocking_request_handler_explanation.py
               :pyobject: TimeoutYieldedRequestHandler.handle
               :dedent:
               :linenos:
               :emphasize-lines: 4,16-18

         .. group-tab:: Asynchronous

            .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_request_handler_explanation.py
               :pyobject: TimeoutYieldedRequestHandler.handle
               :dedent:
               :linenos:
               :emphasize-lines: 4,16-18

   .. tab:: Using ``with`` (Asynchronous only)

      Since all :exc:`BaseException` subclasses are thrown into the generator, you can apply a timeout to the read stream
      using the :term:`asynchronous framework` (the cancellation exception is retrieved in the generator):

      .. tabs::

         .. group-tab:: Using ``asyncio``

            .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_request_handler_explanation.py
               :pyobject: TimeoutContextRequestHandlerAsyncIO.handle
               :dedent:
               :linenos:
               :emphasize-lines: 14,17-18

         .. group-tab:: Using ``trio``

            .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_request_handler_explanation.py
               :pyobject: TimeoutContextRequestHandlerTrio.handle
               :dedent:
               :linenos:
               :emphasize-lines: 14,17-18

         .. group-tab:: Using the ``AsyncBackend`` API

            .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_request_handler_explanation.py
               :pyobject: TimeoutContextRequestHandlerWithClientBackend.handle
               :dedent:
               :linenos:
               :emphasize-lines: 14,17-18

      .. warning::

         Note that this behavior works because the generator is always executed and closed
         in the same asynchronous task for the current implementation.

         This feature is available so that features like :class:`trio.CancelScope` can be used.
         However, it may be removed in a future release.


Sending Packets with socket control messages
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

By using :class:`.SocketAncillary`, you can send SCM data. See the Unix manual page :manpage:`sendmsg(2)` for details.

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/blocking_request_handler_explanation.py
         :pyobject: SCMSendRequestHandler.handle
         :dedent:
         :linenos:
         :emphasize-lines: 7-9

   .. group-tab:: Asynchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_request_handler_explanation.py
         :pyobject: SCMSendRequestHandler.handle
         :dedent:
         :linenos:
         :emphasize-lines: 7-9


Receiving Packets with socket control messages
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

By using :class:`.RecvAncillaryDataParams` and :class:`.SocketAncillary`, you can receive SCM data.
See the Unix manual page :manpage:`recvmsg(2)` for details.

.. warning::

   You must **enable the feature** in the server configuration to make this work.

   .. tabs::

      .. group-tab:: Synchronous

         .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/blocking_request_handler_explanation.py
            :pyobject: SCMRecvRequestHandler.receive_ancillary_data
            :start-after: [start]
            :dedent:
            :linenos:
            :emphasize-lines: 5

      .. group-tab:: Asynchronous

         .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_request_handler_explanation.py
            :pyobject: SCMRecvRequestHandler.receive_ancillary_data
            :start-after: [start]
            :dedent:
            :linenos:
            :emphasize-lines: 5

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/blocking_request_handler_explanation.py
         :pyobject: SCMRecvRequestHandler.handle
         :dedent:
         :linenos:
         :emphasize-lines: 5-6,8

   .. group-tab:: Asynchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_request_handler_explanation.py
         :pyobject: SCMRecvRequestHandler.handle
         :dedent:
         :linenos:
         :emphasize-lines: 5-6,8

.. tip::

   The default buffer size for this operation is approximately 8 KiB. However, you can customize this behavior.

   .. tabs::

      .. group-tab:: Synchronous

         .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/blocking_request_handler_explanation.py
            :pyobject: SCMRecvRequestHandler.example_custom_ancillary_bufsize
            :start-after: [start]
            :dedent:
            :linenos:
            :emphasize-lines: 9

      .. group-tab:: Asynchronous

         .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_request_handler_explanation.py
            :pyobject: SCMRecvRequestHandler.example_custom_ancillary_bufsize
            :start-after: [start]
            :dedent:
            :linenos:
            :emphasize-lines: 9


Client Metadata
---------------

The client's metadata are available via :class:`.UNIXClientAttribute`:

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/blocking_request_handler_explanation.py
         :pyobject: ClientExtraAttributesRequestHandler.handle
         :dedent:
         :linenos:
         :emphasize-lines: 5

   .. group-tab:: Asynchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_request_handler_explanation.py
         :pyobject: ClientExtraAttributesRequestHandler.handle
         :dedent:
         :linenos:
         :emphasize-lines: 5

Service Initialization
----------------------

.. tabs::

   .. group-tab:: Synchronous

      The server will call :meth:`~.BlockingDatagramRequestHandler.service_init` and pass it an :class:`~contextlib.ExitStack`
      at the beginning of the :meth:`~.ThreadedUnixDatagramServer.serve_forever` task to set up the global service.

      This allows you to do something like this:

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/blocking_request_handler_explanation.py
         :pyobject: ServiceInitializationHookRequestHandler
         :start-after: ServiceInitializationHookRequestHandler
         :dedent:
         :linenos:
         :emphasize-lines: 1

   .. group-tab:: Asynchronous

      The server will call :meth:`~.AsyncDatagramRequestHandler.service_init` and pass it an :class:`~contextlib.AsyncExitStack`
      at the beginning of the :meth:`~.AsyncUnixDatagramServer.serve_forever` task to set up the global service.

      This allows you to do something like this:

      .. tabs::

         .. group-tab:: Using ``asyncio``

            .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_request_handler_explanation.py
               :pyobject: ServiceInitializationHookRequestHandlerAsyncIO
               :start-after: ServiceInitializationHookRequestHandlerAsyncIO
               :dedent:
               :linenos:
               :emphasize-lines: 1

         .. group-tab:: Using ``trio``

            .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_request_handler_explanation.py
               :pyobject: ServiceInitializationHookRequestHandlerTrio
               :start-after: ServiceInitializationHookRequestHandlerTrio
               :dedent:
               :linenos:
               :emphasize-lines: 1

         .. group-tab:: Using the ``AsyncBackend`` API

            .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_request_handler_explanation.py
               :pyobject: ServiceInitializationHookRequestHandlerWithServerBackend
               :start-after: ServiceInitializationHookRequestHandlerWithServerBackend
               :dedent:
               :linenos:
               :emphasize-lines: 1,8,15


Low-Level Socket Operations
---------------------------

For low-level operations such as :meth:`~socket.socket.setsockopt`, the server object exposes the sockets through a :class:`.SocketProxy`:

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/blocking_request_handler_explanation.py
         :pyobject: LowLevelSocketOperationsRequestHandler.service_init
         :dedent:
         :linenos:
         :emphasize-lines: 6-8

   .. group-tab:: Asynchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_request_handler_explanation.py
         :pyobject: LowLevelSocketOperationsRequestHandler.service_init
         :dedent:
         :linenos:
         :emphasize-lines: 6-8


Per-client variables (``contextvars`` integration)
--------------------------------------------------

.. tabs::

   .. group-tab:: Synchronous

      The :class:`.ThreadedUnixDatagramServer` supports per-task :external+python:doc:`context variables <library/contextvars>`.
      You can use this feature in your request handler:

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/blocking_request_handler_explanation.py
         :pyobject: ClientContextRequestHandler
         :dedent:
         :linenos:

      .. tip::

         It is possible to initialize the context to be copied in :meth:`~.BlockingDatagramRequestHandler.service_init`.

         This means that the :meth:`contextvars.ContextVar.set` calls made in ``service_init()`` will be applied
         to subsequent client tasks.

   .. group-tab:: Asynchronous

      If your :term:`asynchronous framework` supports per-task :external+python:doc:`context variables <library/contextvars>`,
      you can use this feature in your request handler:

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_request_handler_explanation.py
         :pyobject: ClientContextRequestHandler
         :dedent:
         :linenos:

      .. tip::

         It is possible to initialize the context to be copied in :meth:`~.AsyncDatagramRequestHandler.service_init`.

         This means that the :meth:`contextvars.ContextVar.set` calls made in ``service_init()`` will be applied
         to subsequent client tasks.


Server Object
=============

A basic example of how to run the server:

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/threaded_server.py
         :linenos:

   .. group-tab:: Asynchronous

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_server.py
         :linenos:
