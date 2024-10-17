*******************************
Asynchronous Backend Engine API
*******************************

.. automodule:: easynetwork.lowlevel.api_async.backend

.. contents:: Table of Contents
   :local:
   :depth: 1

------

Introduction
============

In order not to depend on a single implementation of asynchronous operations (e.g. ``asyncio``), here is a mini-framework
to manage different implementations and keep EasyNetwork unaware of the library used.

.. admonition:: Why not just use anyio directly?

   Short answer: Because I don't want to.

   .. collapse:: Click here to expand/collapse the long answer

      The main problem with :mod:`anyio` is the simple fact that it is a framework that already encapsulates the sockets
      without providing a way to manipulate the underlying transport, **and this is normal**; it would be a horror to maintain.

      But as a result, the high-level API does not expose the features I need, such as:

      * :class:`anyio.abc.ByteReceiveStream` not having a ``receive_into(buffer)`` method;

      * Implementing zero copy sending of multi-byte buffers with :meth:`~socket.socket.sendmsg`;

      * :func:`anyio.connect_tcp`, :func:`anyio.connect_unix` and :func:`anyio.create_udp_socket` not taking an already connected socket;

      * Missing implementation of UNIX datagram sockets;

      * Managed tasks like :class:`asyncio.Task`;

      * and the list goes on...

      The second problem is having anyio as a dependency. :mod:`asyncio` is part of the standard library, so why would I use an external
      (and large) project to manage :mod:`asyncio` and make it mandatory?
      Also, it would be heavier to write :mod:`asyncio`-only code if :mod:`anyio` is not installed.

Usage
-----

Use The Interface Provided By The High-level API
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

All asynchronous objects relying on an :class:`AsyncBackend` object have a ``backend()`` method:

* High-level clients ( :meth:`.AbstractAsyncNetworkClient.backend` ).

* High-level servers ( :meth:`.AbstractAsyncNetworkServer.backend` ).

   * This includes the clients created for the request handlers ( :meth:`.AsyncBaseClientInterface.backend` ).

* Low-level endpoints ( :meth:`.AsyncStreamEndpoint.backend` and :meth:`.AsyncDatagramEndpoint.backend` ).

* Low-level servers ( :meth:`.AsyncStreamServer.backend` and :meth:`.AsyncDatagramServer.backend` ).

   * This includes the clients created for the request handlers:

      * AsyncStreamServer: :meth:`.ConnectedStreamClient.backend`.

      * AsyncDatagramServer: :meth:`.DatagramClientContext.backend`.

* Data transport adapters ( :meth:`.AsyncBaseTransport.backend` ).

* Concurrent Executors ( :meth:`.AsyncExecutor.backend` ).

Obtain An Object By Yourself
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

You can use :func:`.new_builtin_backend` to have a backend instance:

>>> from easynetwork.lowlevel.api_async.backend.utils import new_builtin_backend
>>> new_builtin_backend("asyncio")
<AsyncIOBackend object at ...>
>>> new_builtin_backend("trio")
<TrioBackend object at ...>

You can also let :mod:`sniffio` determine which backend should be used via :func:`.ensure_backend`:

>>> from easynetwork.lowlevel.api_async.backend.utils import ensure_backend
>>> import asyncio, trio
>>>
>>> async def main():
...     return ensure_backend(None)
...
>>> asyncio.run(main())
<AsyncIOBackend object at ...>
>>> trio.run(main)
<TrioBackend object at ...>

------

Backend Interface
=================

.. automodule:: easynetwork.lowlevel.api_async.backend.abc

.. I don't understand why __new__ and __init__ are shown here o_0
.. autoclass:: AsyncBackend
   :exclude-members: __new__, __init__

.. contents:: :class:`AsyncBackend`'s methods
   :local:

Runners
-------

.. automethod:: AsyncBackend.bootstrap

Coroutines And Tasks
--------------------

Sleeping
^^^^^^^^

.. automethod:: AsyncBackend.coro_yield

.. automethod:: AsyncBackend.sleep

.. automethod:: AsyncBackend.sleep_forever

.. automethod:: AsyncBackend.sleep_until

.. automethod:: AsyncBackend.current_time

Task Cancellation
^^^^^^^^^^^^^^^^^

.. automethod:: AsyncBackend.get_cancelled_exc_class

Shielding From Task Cancellation
""""""""""""""""""""""""""""""""

.. automethod:: AsyncBackend.cancel_shielded_coro_yield

.. automethod:: AsyncBackend.ignore_cancellation

Creating Concurrent Tasks
^^^^^^^^^^^^^^^^^^^^^^^^^

.. automethod:: AsyncBackend.gather

.. automethod:: AsyncBackend.create_task_group

.. autoclass:: TaskGroup
   :members:
   :special-members: __aenter__, __aexit__

.. autoclass:: Task
   :members:

Introspection
^^^^^^^^^^^^^

.. automethod:: AsyncBackend.get_current_task

.. autoclass:: TaskInfo
   :members:

Timeouts
^^^^^^^^

.. automethod:: AsyncBackend.open_cancel_scope

.. automethod:: AsyncBackend.move_on_after

.. automethod:: AsyncBackend.move_on_at

.. automethod:: AsyncBackend.timeout

.. automethod:: AsyncBackend.timeout_at

.. autoclass:: CancelScope
   :members:

Networking
----------

DNS
^^^

.. automethod:: AsyncBackend.getaddrinfo

.. automethod:: AsyncBackend.getnameinfo

Opening Network Connections
^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. automethod:: AsyncBackend.create_tcp_connection

.. automethod:: AsyncBackend.create_unix_stream_connection

.. automethod:: AsyncBackend.wrap_stream_socket

.. automethod:: AsyncBackend.create_udp_endpoint

.. automethod:: AsyncBackend.create_unix_datagram_endpoint

.. automethod:: AsyncBackend.wrap_connected_datagram_socket

Creating Network Servers
^^^^^^^^^^^^^^^^^^^^^^^^

.. automethod:: AsyncBackend.create_tcp_listeners

.. automethod:: AsyncBackend.create_unix_stream_listener

.. automethod:: AsyncBackend.create_udp_listeners

.. automethod:: AsyncBackend.create_unix_datagram_listener


Synchronization Primitives
--------------------------

Locks
^^^^^

.. automethod:: AsyncBackend.create_lock

.. automethod:: AsyncBackend.create_fair_lock

.. autoprotocol:: ILock

Events
^^^^^^

.. automethod:: AsyncBackend.create_event

.. autoprotocol:: IEvent

Condition Variables
^^^^^^^^^^^^^^^^^^^

.. automethod:: AsyncBackend.create_condition_var

.. autoprotocol:: ICondition

Concurrency And Multithreading
------------------------------

Running Blocking Code
^^^^^^^^^^^^^^^^^^^^^

.. automethod:: AsyncBackend.run_in_thread

Scheduling From Other Threads
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. automethod:: AsyncBackend.create_threads_portal

.. autoclass:: ThreadsPortal
   :members:
   :special-members: __aenter__, __aexit__


Useful tools
============

.. automodule:: easynetwork.lowlevel.api_async.backend.utils
   :no-docstring:
   :members:
