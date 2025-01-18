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

#. Derive a class from :class:`.AsyncDatagramRequestHandler` and redefine its :meth:`~.AsyncDatagramRequestHandler.handle` method;
   this method will process incoming requests.

#. Instantiate the :class:`.AsyncUnixDatagramServer` class passing it the server's address, the :term:`protocol object`
   and the request handler instance.

#. Call :meth:`~.AsyncUnixDatagramServer.serve_forever` to process requests.

Writing :term:`coroutine functions <coroutine function>` is mandatory to use this server.

.. seealso::

   :pep:`492` — Coroutines with async and await syntax
      The proposal to introduce native coroutines in Python with :keyword:`async` and :keyword:`await` syntax.

   :external+python:doc:`library/asyncio`
      If you are not familiar with async/await syntax, you can use the standard library to get started with coroutines.


Request Handler Objects
=======================

.. note::

   Unlike :class:`socketserver.BaseRequestHandler`, there is **only one** :class:`.AsyncDatagramRequestHandler` instance for the entire service.


Here is a simple example:

.. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/simple_request_handler.py
   :linenos:

.. warning::

   Sending socket control messages ( with :manpage:`sendmsg(2)` ) is not supported yet.

.. warning::

   Receiving socket control messages ( with :manpage:`recvmsg(2)` ) is not supported yet.

Using ``handle()`` Generator
----------------------------

.. important::
   There will always be only one active generator per client.
   All the pending datagrams received while the generator is running are queued.

   This behavior is designed to act like a stream request handler.


Minimum Requirements
^^^^^^^^^^^^^^^^^^^^

.. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/request_handler_explanation.py
   :pyobject: MinimumRequestHandler.handle
   :dedent:
   :linenos:


Refuse datagrams
^^^^^^^^^^^^^^^^

Your UDP socket can receive datagrams from anywhere. You may want to control who can send you information.

.. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/request_handler_explanation.py
   :pyobject: SkipDatagramRequestHandler.handle
   :dedent:
   :linenos:
   :emphasize-lines: 5-8

Error Handling
^^^^^^^^^^^^^^

.. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/request_handler_explanation.py
   :pyobject: ErrorHandlingInRequestHandler.handle
   :dedent:
   :linenos:

.. warning::

   You should always log or re-raise a bare :exc:`Exception` thrown in your generator.

   .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/request_handler_explanation.py
      :pyobject: ErrorHandlingInRequestHandler.handle
      :dedent:
      :linenos:
      :start-at: except Exception
      :end-at: InternalError()
      :emphasize-lines: 2-3


Having Multiple ``yield`` Statements
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/request_handler_explanation.py
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

      It is possible to send the timeout delay to the parent task:

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/request_handler_explanation.py
         :pyobject: TimeoutYieldedRequestHandler.handle
         :dedent:
         :linenos:
         :emphasize-lines: 4,16-18

   .. tab:: Using ``with``

      Since all :exc:`BaseException` subclasses are thrown into the generator, you can apply a timeout to the read stream
      using the :term:`asynchronous framework` (the cancellation exception is retrieved in the generator):

      .. tabs::

         .. group-tab:: Using ``asyncio``

            .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/request_handler_explanation.py
               :pyobject: TimeoutContextRequestHandlerAsyncIO.handle
               :dedent:
               :linenos:
               :emphasize-lines: 14,17-18

         .. group-tab:: Using ``trio``

            .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/request_handler_explanation.py
               :pyobject: TimeoutContextRequestHandlerTrio.handle
               :dedent:
               :linenos:
               :emphasize-lines: 14,17-18

         .. group-tab:: Using the ``AsyncBackend`` API

            .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/request_handler_explanation.py
               :pyobject: TimeoutContextRequestHandlerWithClientBackend.handle
               :dedent:
               :linenos:
               :emphasize-lines: 14,17-18

      .. warning::

         Note that this behavior works because the generator is always executed and closed
         in the same asynchronous task for the current implementation.

         This feature is available so that features like :class:`trio.CancelScope` can be used.
         However, it may be removed in a future release.


Client Metadata
---------------

The client's metadata are available via :class:`.UNIXClientAttribute`:

.. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/request_handler_explanation.py
   :pyobject: ClientExtraAttributesRequestHandler.handle
   :dedent:
   :linenos:
   :emphasize-lines: 5

.. warning::

   The socket option ``SO_PASSCRED`` on Linux has no effect for now. This will be handled in the future.


Service Initialization
----------------------

The server will call :meth:`~.AsyncDatagramRequestHandler.service_init` and pass it an :class:`~contextlib.AsyncExitStack`
at the beginning of the :meth:`~.AsyncUnixDatagramServer.serve_forever` task to set up the global service.

This allows you to do something like this:

.. tabs::

   .. group-tab:: Using ``asyncio``

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/request_handler_explanation.py
         :pyobject: ServiceInitializationHookRequestHandlerAsyncIO
         :start-after: ServiceInitializationHookRequestHandlerAsyncIO
         :dedent:
         :linenos:
         :emphasize-lines: 1

   .. group-tab:: Using ``trio``

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/request_handler_explanation.py
         :pyobject: ServiceInitializationHookRequestHandlerTrio
         :start-after: ServiceInitializationHookRequestHandlerTrio
         :dedent:
         :linenos:
         :emphasize-lines: 1

   .. group-tab:: Using the ``AsyncBackend`` API

      .. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/request_handler_explanation.py
         :pyobject: ServiceInitializationHookRequestHandlerWithServerBackend
         :start-after: ServiceInitializationHookRequestHandlerWithServerBackend
         :dedent:
         :linenos:
         :emphasize-lines: 1,8,15


Per-client variables (``contextvars`` integration)
--------------------------------------------------

If your :term:`asynchronous framework` supports per-task :external+python:doc:`context variables <library/contextvars>`,
you can use this feature in your request handler:

.. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/request_handler_explanation.py
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

.. literalinclude:: ../../_include/examples/alternatives/unix_datagram_servers/async_server.py
   :linenos:
