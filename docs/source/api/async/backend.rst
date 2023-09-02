*******************************
Asynchronous backend engine API
*******************************

.. contents:: Table of Contents
   :local:
   :depth: 1

------

Introduction
============

.. todo::

   Explain this big thing.


Backend interface
=================

.. automodule:: easynetwork.api_async.backend.abc
   :no-docstring:

.. autoclass:: AsyncBackend

.. contents:: :class:`AsyncBackend`'s methods
   :local:

Runners
-------

.. automethod:: AsyncBackend.bootstrap

.. automethod:: AsyncBackend.new_runner

.. autoclass:: Runner
   :members:
   :special-members: __enter__, __exit__

Coroutines and Tasks
--------------------

Sleeping
^^^^^^^^

.. automethod:: AsyncBackend.coro_yield

.. automethod:: AsyncBackend.sleep

.. automethod:: AsyncBackend.sleep_forever

.. automethod:: AsyncBackend.sleep_until

.. automethod:: AsyncBackend.current_time

Task cancellation
^^^^^^^^^^^^^^^^^

.. automethod:: AsyncBackend.get_cancelled_exc_class

Shielding from task cancellation
""""""""""""""""""""""""""""""""

.. automethod:: AsyncBackend.cancel_shielded_coro_yield

.. automethod:: AsyncBackend.ignore_cancellation

Creating concurrent tasks
^^^^^^^^^^^^^^^^^^^^^^^^^

.. automethod:: AsyncBackend.create_task_group

.. autoclass:: TaskGroup
   :members:
   :special-members: __aenter__, __aexit__

.. autoclass:: Task
   :members:

Spawning system tasks
"""""""""""""""""""""

.. automethod:: AsyncBackend.spawn_task

.. autoclass:: SystemTask
   :members:

Timeouts
^^^^^^^^

.. automethod:: AsyncBackend.move_on_after

.. automethod:: AsyncBackend.move_on_at

.. automethod:: AsyncBackend.timeout

.. automethod:: AsyncBackend.timeout_at

.. autoclass:: TimeoutHandle
   :members:

Networking
----------

Opening network connections
^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. automethod:: AsyncBackend.create_tcp_connection

.. automethod:: AsyncBackend.create_ssl_over_tcp_connection

.. automethod:: AsyncBackend.wrap_tcp_client_socket

.. automethod:: AsyncBackend.wrap_ssl_over_tcp_client_socket

.. automethod:: AsyncBackend.create_udp_endpoint

.. automethod:: AsyncBackend.wrap_udp_socket

Creating network servers
^^^^^^^^^^^^^^^^^^^^^^^^

.. automethod:: AsyncBackend.create_tcp_listeners

.. automethod:: AsyncBackend.create_ssl_over_tcp_listeners

Socket adapter classes
^^^^^^^^^^^^^^^^^^^^^^

.. autoclass:: AsyncBaseSocketAdapter
   :members:
   :special-members: __aenter__, __aexit__

.. autoclass:: AsyncStreamSocketAdapter
   :members:

.. autoclass:: AsyncHalfCloseableStreamSocketAdapter
   :members:

.. autoclass:: AsyncDatagramSocketAdapter
   :members:

.. autoclass:: AsyncListenerSocketAdapter
   :members:

.. autoclass:: AcceptedSocket
   :members:


Synchronization Primitives
--------------------------

Locks
^^^^^

.. automethod:: AsyncBackend.create_lock

.. autoprotocol:: ILock

Events
^^^^^^

.. automethod:: AsyncBackend.create_event

.. autoprotocol:: IEvent

Condition variables
^^^^^^^^^^^^^^^^^^^

.. automethod:: AsyncBackend.create_condition_var

.. autoprotocol:: ICondition

Concurrency and Multithreading
------------------------------

Running blocking code
^^^^^^^^^^^^^^^^^^^^^

.. automethod:: AsyncBackend.run_in_thread

Scheduling from other threads
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. automethod:: AsyncBackend.create_threads_portal

.. autoclass:: ThreadsPortal
   :members:

``concurrent.futures`` integration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. automethod:: AsyncBackend.wait_future

.. seealso::

   :class:`.AsyncExecutor` class.


Backend factory
===============

.. automodule:: easynetwork.api_async.backend.factory
   :no-docstring:

.. todo::

   Document backend factory usage.

.. autoclass:: AsyncBackendFactory
   :members:
   :exclude-members: GROUP_NAME


Tasks utilities
===============

.. automodule:: easynetwork.api_async.backend.tasks
   :no-docstring:

.. autoclass:: SingleTaskRunner
   :members:


Concurrency and Multithreading (``concurrent.futures`` integration)
===================================================================

.. automodule:: easynetwork.api_async.backend.futures
   :no-docstring:

.. autoclass:: AsyncExecutor
   :members:
   :special-members: __aenter__, __aexit__

.. autoclass:: AsyncThreadPoolExecutor(backend, *, max_workers=..., thread_name_prefix=..., initializer=..., initargs=..., **kwargs)
   :members:
