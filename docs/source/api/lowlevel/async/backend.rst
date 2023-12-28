*******************************
Asynchronous Backend Engine API
*******************************

.. contents:: Table of Contents
   :local:
   :depth: 1

------

Introduction
============

.. todo::

   Explain this big thing.


Backend Interface
=================

.. automodule:: easynetwork.lowlevel.api_async.backend.abc
   :no-docstring:

.. autoclass:: AsyncBackend

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

Opening Network Connections
^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. automethod:: AsyncBackend.create_tcp_connection

.. automethod:: AsyncBackend.create_ssl_over_tcp_connection

.. automethod:: AsyncBackend.wrap_stream_socket

.. automethod:: AsyncBackend.wrap_ssl_over_stream_socket_client_side

.. automethod:: AsyncBackend.create_udp_endpoint

.. automethod:: AsyncBackend.wrap_connected_datagram_socket

Creating Network Servers
^^^^^^^^^^^^^^^^^^^^^^^^

.. automethod:: AsyncBackend.create_tcp_listeners

.. automethod:: AsyncBackend.create_ssl_over_tcp_listeners

.. automethod:: AsyncBackend.create_udp_listeners


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


Backend Factory
===============

.. automodule:: easynetwork.lowlevel.api_async.backend.factory
   :no-docstring:

.. todo::

   Document backend factory usage.

.. autoclass:: AsyncBackendFactory
   :members:
   :exclude-members: GROUP_NAME
