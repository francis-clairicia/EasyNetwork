***********
Servers API
***********

Asynchronous network server interfaces

.. currentmodule:: easynetwork.servers

.. contents:: Table of Contents
   :local:

------

Abstract Base Class
===================

.. autoclass:: easynetwork.servers.abc::AbstractAsyncNetworkServer
   :members:
   :special-members: __aenter__, __aexit__

.. autoprotocol:: easynetwork.servers.abc::SupportsEventSet


TCP Implementation
==================

.. autoclass:: AsyncTCPNetworkServer
   :members:
   :inherited-members:

UDP Implementation
==================

.. autoclass:: AsyncUDPNetworkServer
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
