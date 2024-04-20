***********
Servers API
***********

.. automodule:: easynetwork.servers

.. contents:: Table of Contents
   :local:

------

Asynchronous Server Objects (``async def``)
===========================================

Abstract Base Class
-------------------

.. autoclass:: easynetwork.servers.abc::AbstractAsyncNetworkServer
   :members:
   :special-members: __aenter__, __aexit__

.. autoprotocol:: easynetwork.servers.abc::SupportsEventSet


TCP Implementation
------------------

.. autoclass:: AsyncTCPNetworkServer
   :members:
   :inherited-members:

UDP Implementation
------------------

.. autoclass:: AsyncUDPNetworkServer
   :members:
   :inherited-members:


Synchronous Server Objects
==========================

Abstract Base Class
-------------------

.. autoclass:: easynetwork.servers.abc::AbstractNetworkServer
   :members:
   :special-members: __enter__, __exit__

TCP Implementation
------------------

.. autoclass:: StandaloneTCPNetworkServer
   :members:
   :inherited-members:

UDP Implementation
------------------

.. autoclass:: StandaloneUDPNetworkServer
   :members:
   :inherited-members:



Request Handler Interface
=========================

.. currentmodule:: easynetwork.servers.handlers

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
