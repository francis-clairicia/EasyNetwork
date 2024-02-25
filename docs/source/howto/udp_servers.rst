********************
How-to — UDP Servers
********************

.. include:: ../_include/sync-async-variants.rst

.. contents:: Table of Contents
   :local:

------

Introduction
============

Creating a UDP server requires several steps:

#. Derive a class from :class:`.AsyncDatagramRequestHandler` and redefine its :meth:`~.AsyncDatagramRequestHandler.handle` method;
   this method will process incoming requests.

#. Instantiate the :class:`.AsyncUDPNetworkServer` class passing it the server's address, the :term:`protocol object`
   and the request handler instance.

#. Call :meth:`~.AsyncUDPNetworkServer.serve_forever` to process requests.


Request Handler Objects
=======================

.. note::

   Unlike :class:`socketserver.BaseRequestHandler`, there is **only one** :class:`.AsyncDatagramRequestHandler` instance for the entire service.


Here is a simple example:

.. literalinclude:: ../_include/examples/howto/udp_servers/simple_request_handler.py
   :linenos:


Using ``handle()`` Generator
----------------------------

.. important::
   There will always be only one active generator per client.
   All the pending datagrams received while the generator is running are queued.

   This behavior is designed to act like a stream request handler.


Minimum Requirements
^^^^^^^^^^^^^^^^^^^^

.. literalinclude:: ../_include/examples/howto/udp_servers/request_handler_explanation.py
   :pyobject: MinimumRequestHandler.handle
   :dedent:
   :linenos:


Refuse datagrams
^^^^^^^^^^^^^^^^

Your UDP socket can receive datagrams from anywhere. You may want to control who can send you information.

.. literalinclude:: ../_include/examples/howto/udp_servers/request_handler_explanation.py
   :pyobject: SkipDatagramRequestHandler.handle
   :dedent:
   :linenos:
   :emphasize-lines: 5-8

Error Handling
^^^^^^^^^^^^^^

.. literalinclude:: ../_include/examples/howto/udp_servers/request_handler_explanation.py
   :pyobject: ErrorHandlingInRequestHandler.handle
   :dedent:
   :linenos:

.. warning::

   You should always log or re-raise a bare :exc:`Exception` thrown in your generator.

   .. literalinclude:: ../_include/examples/howto/udp_servers/request_handler_explanation.py
      :pyobject: ErrorHandlingInRequestHandler.handle
      :dedent:
      :linenos:
      :start-at: except Exception
      :end-at: InternalError()
      :emphasize-lines: 2-3


Having Multiple ``yield`` Statements
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. literalinclude:: ../_include/examples/howto/udp_servers/request_handler_explanation.py
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

      .. literalinclude:: ../_include/examples/howto/udp_servers/request_handler_explanation.py
         :pyobject: TimeoutYieldedRequestHandler.handle
         :dedent:
         :linenos:
         :emphasize-lines: 4,15-17

   .. tab:: Using ``with``

      Since all :exc:`BaseException` subclasses are thrown into the generator, you can apply a timeout to the read stream
      using the asynchronous framework (the cancellation exception is retrieved in the generator):

      .. literalinclude:: ../_include/examples/howto/udp_servers/request_handler_explanation.py
         :pyobject: TimeoutContextRequestHandler.handle
         :dedent:
         :linenos:
         :emphasize-lines: 14,17-18

      .. warning::

         Note that this behavior works because the generator is always executed and closed
         in the same asynchronous task for the current implementation.

         This feature is available so that features like ``anyio.CancelScope`` can be used.
         However, it may be removed in a future release.


Service Initialization
----------------------

The server will call :meth:`~.AsyncDatagramRequestHandler.service_init` and pass it an :class:`~contextlib.AsyncExitStack`
at the beginning of the :meth:`~.AsyncUDPNetworkServer.serve_forever` task to set up the global service.

This allows you to do something like this:

.. literalinclude:: ../_include/examples/howto/udp_servers/request_handler_explanation.py
   :pyobject: ServiceInitializationHookRequestHandler
   :start-after: ServiceInitializationHookRequestHandler
   :dedent:
   :linenos:
   :emphasize-lines: 1


Server Object
=============

A basic example of how to run the server:

.. literalinclude:: ../_include/examples/howto/udp_servers/async_server.py
   :linenos:

.. seealso::

   :doc:`/tutorials/echo_client_server_udp`
      A working example of the server implementation.
