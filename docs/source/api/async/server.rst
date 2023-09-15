***********
Servers API
***********

.. automodule:: easynetwork.api_async.server

.. contents:: Table of Contents
   :local:

------

Abstract Base Class
===================

.. autoclass:: AbstractAsyncNetworkServer
   :members:
   :special-members: __aenter__, __aexit__

.. autoprotocol:: easynetwork.api_async.server.abc::SupportsEventSet


TCP Implementation
==================

.. autoclass:: AsyncTCPNetworkServer
   :members:

UDP Implementation
==================

.. autoclass:: AsyncUDPNetworkServer
   :members:


Request Handler Interface
=========================

.. autoclass:: AsyncBaseRequestHandler
   :members:

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
