***********
Servers API
***********

.. automodule:: easynetwork.servers

.. contents:: Table of Contents
   :local:

------

Abstract Base Classes
=====================

.. automodule:: easynetwork.servers.abc
   :members:
   :special-members: __aenter__, __aexit__


Asynchronous Server Objects (``async def``)
===========================================

TCP Implementation
------------------

.. automodule:: easynetwork.servers.async_tcp
   :members:
   :inherited-members:

UDP Implementation
------------------

.. automodule:: easynetwork.servers.async_udp
   :members:
   :inherited-members:


Synchronous Server Objects
==========================

TCP Implementation
------------------

.. automodule:: easynetwork.servers.standalone_tcp
   :members:
   :inherited-members:

UDP Implementation
------------------

.. automodule:: easynetwork.servers.standalone_udp
   :members:
   :inherited-members:


Request Handler Interface
=========================

.. automodule:: easynetwork.servers.handlers

.. autoclass:: AsyncStreamRequestHandler
   :members:

.. autoclass:: AsyncDatagramRequestHandler
   :members:

Client API
----------

.. autoclass:: AsyncBaseClientInterface
   :members:

.. autoclass:: AsyncStreamClient
   :members:

.. autoclass:: AsyncDatagramClient
   :members:
   :special-members: __eq__, __hash__


------

Server implementation tools
===========================

.. toctree::
   :maxdepth: 1

   threads_helper
   misc
