***********
Clients API
***********

.. automodule:: easynetwork.api_async.client

.. contents:: Table of Contents
   :local:

------

Abstract Base Class
===================

.. autoclass:: AbstractAsyncNetworkClient
   :members:
   :special-members: __aenter__, __aexit__


TCP Implementation
==================

.. autoclass:: AsyncTCPNetworkClient
   :members:

UDP Implementation
==================

.. autoclass:: AsyncUDPNetworkClient
   :members:
   :exclude-members: iter_received_packets


Generic UDP Endpoint
--------------------

.. autoclass:: AsyncUDPNetworkEndpoint
   :members:
   :special-members: __aenter__, __aexit__
