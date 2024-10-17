*********************************
Alternative — Unix Stream Servers
*********************************

.. include:: ../../_include/sync-async-variants.rst

.. contents:: Table of Contents
   :local:

------

Introduction
============

Creating a Unix server requires several steps:

#. Derive a class from :class:`.AsyncStreamRequestHandler` and redefine its :meth:`~.AsyncStreamRequestHandler.handle` method;
   this method will process incoming requests.

#. Instantiate the :class:`.AsyncUnixStreamServer` class passing it the server's address, the :term:`protocol object`
   and the request handler instance.

#. Call :meth:`~.AsyncUnixStreamServer.serve_forever` to process requests.

Writing :term:`coroutine functions <coroutine function>` is mandatory to use this server.

.. seealso::

   :pep:`492` — Coroutines with async and await syntax
      The proposal to introduce native coroutines in Python with :keyword:`async` and :keyword:`await` syntax.

   :external+python:doc:`library/asyncio`
      If you are not familiar with async/await syntax, you can use the standard library to get started with coroutines.


Request Handler Objects
=======================

.. note::

   Unlike :class:`socketserver.BaseRequestHandler`, there is **only one** :class:`.AsyncStreamRequestHandler` instance for the entire service.


Here is a simple example:

.. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/simple_request_handler.py
   :linenos:

.. warning::

   Sending socket control messages ( with :manpage:`sendmsg(2)` ) is not supported yet.

.. warning::

   Receiving socket control messages ( with :manpage:`recvmsg(2)` ) is not supported yet.

Using ``handle()`` Generator
----------------------------

.. seealso::

   :pep:`525` — Asynchronous Generators
      The proposal that expanded on :pep:`492` by adding generator capabilities to coroutine functions.


Minimum Requirements
^^^^^^^^^^^^^^^^^^^^

.. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/request_handler_explanation.py
   :pyobject: MinimumRequestHandler.handle
   :dedent:
   :linenos:


Closing the connection
^^^^^^^^^^^^^^^^^^^^^^

.. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/request_handler_explanation.py
   :pyobject: ConnectionCloseRequestHandler.handle
   :dedent:
   :linenos:
   :emphasize-lines: 11

.. tip::

   You can use :func:`contextlib.aclosing` to close the client at the generator exit.

   .. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/request_handler_explanation.py
      :pyobject: ConnectionCloseWithContextRequestHandler.handle
      :dedent:
      :linenos:
      :emphasize-lines: 5

.. important::

   The connection is forcibly closed under the following conditions:

   * ``handle()`` raises an exception.

   * ``handle()`` returns *before* the first :keyword:`yield` statement.

      .. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/request_handler_explanation.py
         :pyobject: ConnectionCloseBeforeYieldRequestHandler.handle
         :dedent:
         :linenos:
         :emphasize-lines: 5-6


Error Handling
^^^^^^^^^^^^^^

.. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/request_handler_explanation.py
   :pyobject: ErrorHandlingInRequestHandler.handle
   :dedent:
   :linenos:

.. note::

   ``handle()`` will never get a :exc:`ConnectionError` subclass. In case of an unexpected disconnect, the generator is closed,
   so you should handle :exc:`GeneratorExit` instead.

.. warning::

   You should always log or re-raise a bare :exc:`Exception` thrown in your generator.

   .. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/request_handler_explanation.py
      :pyobject: ErrorHandlingInRequestHandler.handle
      :dedent:
      :linenos:
      :start-at: except Exception
      :end-at: InternalError()
      :emphasize-lines: 2-3


Having Multiple ``yield`` Statements
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/request_handler_explanation.py
   :pyobject: MultipleYieldInRequestHandler.handle
   :dedent:
   :linenos:
   :emphasize-lines: 5,12


.. tip::

   The number of :keyword:`yield` allowed is... infinite!

   You can take advantage of this by having an internal main loop inside the generator:

   .. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/request_handler_explanation.py
      :pyobject: ClientLoopInRequestHandler.handle
      :dedent:
      :linenos:


Cancellation And Timeouts
^^^^^^^^^^^^^^^^^^^^^^^^^

.. tabs::

   .. tab:: Using ``yield`` (Recommended)

      It is possible to send the timeout delay to the parent task:

      .. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/request_handler_explanation.py
         :pyobject: TimeoutYieldedRequestHandler.handle
         :dedent:
         :linenos:
         :emphasize-lines: 4,7-9

   .. tab:: Using ``with``

      Since all :exc:`BaseException` subclasses are thrown into the generator, you can apply a timeout to the read stream
      using the :term:`asynchronous framework` (the cancellation exception is retrieved in the generator):

      .. tabs::

         .. group-tab:: Using ``asyncio``

            .. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/request_handler_explanation.py
               :pyobject: TimeoutContextRequestHandlerAsyncIO.handle
               :dedent:
               :linenos:
               :emphasize-lines: 6,9-10

         .. group-tab:: Using ``trio``

            .. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/request_handler_explanation.py
               :pyobject: TimeoutContextRequestHandlerTrio.handle
               :dedent:
               :linenos:
               :emphasize-lines: 6,9-10

         .. group-tab:: Using the ``AsyncBackend`` API

            .. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/request_handler_explanation.py
               :pyobject: TimeoutContextRequestHandlerWithClientBackend.handle
               :dedent:
               :linenos:
               :emphasize-lines: 6,9-10

      .. warning::

         Note that this behavior works because the generator is always executed and closed
         in the same asynchronous task for the current implementation.

         This feature is available so that features like :class:`trio.CancelScope` can be used.
         However, it may be removed in a future release.


Connecting/Disconnecting Hooks
------------------------------

You can override :meth:`~.AsyncStreamRequestHandler.on_connection` and :meth:`~.AsyncStreamRequestHandler.on_disconnection` methods:

* :meth:`~.AsyncStreamRequestHandler.on_connection` is called on client task startup.

* :meth:`~.AsyncStreamRequestHandler.on_disconnection` is called on client task teardown.

.. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/request_handler_explanation.py
   :pyobject: ClientConnectionHooksRequestHandler
   :start-after: ClientConnectionHooksRequestHandler
   :dedent:
   :linenos:
   :emphasize-lines: 1,7


Wait For Client Data On Connection
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If you need to use the read stream, :meth:`~.AsyncStreamRequestHandler.on_connection` can be an asynchronous generator instead of
a coroutine function:

.. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/request_handler_explanation.py
   :pyobject: ClientConnectionAsyncGenRequestHandler
   :start-after: ClientConnectionAsyncGenRequestHandler
   :dedent:
   :linenos:
   :emphasize-lines: 6


Client Metadata
---------------

The client's metadata are available via :class:`.UNIXClientAttribute`:

.. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/request_handler_explanation.py
   :pyobject: ClientExtraAttributesRequestHandler.handle
   :dedent:
   :linenos:
   :emphasize-lines: 5

.. warning::

   The socket option ``SO_PASSCRED`` on Linux has no effect for now. This will be handled in the future.


Service Initialization
----------------------

The server will call :meth:`~.AsyncStreamRequestHandler.service_init` and pass it an :class:`~contextlib.AsyncExitStack`
at the beginning of the :meth:`~.AsyncUnixStreamServer.serve_forever` task to set up the global service.

This allows you to do something like this:

.. tabs::

   .. group-tab:: Using ``asyncio``

      .. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/request_handler_explanation.py
         :pyobject: ServiceInitializationHookRequestHandlerAsyncIO
         :start-after: ServiceInitializationHookRequestHandlerAsyncIO
         :dedent:
         :linenos:
         :emphasize-lines: 1

   .. group-tab:: Using ``trio``

      .. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/request_handler_explanation.py
         :pyobject: ServiceInitializationHookRequestHandlerTrio
         :start-after: ServiceInitializationHookRequestHandlerTrio
         :dedent:
         :linenos:
         :emphasize-lines: 1

   .. group-tab:: Using the ``AsyncBackend`` API

      .. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/request_handler_explanation.py
         :pyobject: ServiceInitializationHookRequestHandlerWithServerBackend
         :start-after: ServiceInitializationHookRequestHandlerWithServerBackend
         :dedent:
         :linenos:
         :emphasize-lines: 1,8,15


Per-client variables (``contextvars`` integration)
--------------------------------------------------

If your :term:`asynchronous framework` supports per-task :external+python:doc:`context variables <library/contextvars>`,
you can use this feature in your request handler:

.. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/request_handler_explanation.py
   :pyobject: ClientContextRequestHandler
   :dedent:
   :linenos:

.. tip::

   It is possible to initialize the context to be copied in :meth:`~.AsyncStreamRequestHandler.service_init`.

   This means that the :meth:`contextvars.ContextVar.set` calls made in ``service_init()`` will be applied
   to subsequent client tasks.

.. warning::

   There is no context isolation between :meth:`~.AsyncStreamRequestHandler.handle` calls.

   This means that the :meth:`contextvars.ContextVar.set` calls made in ``handle()`` are applied to whole client task.


Server Object
=============

A basic example of how to run the server:

.. literalinclude:: ../../_include/examples/alternatives/unix_stream_servers/async_server.py
   :linenos:
