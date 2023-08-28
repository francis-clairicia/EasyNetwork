***********
Clients API
***********

.. automodule:: easynetwork.api_async.client

.. contents:: Table of Contents
   :local:

------

Abstract base class
===================

.. autoclass:: AbstractAsyncNetworkClient
   :members:
   :special-members: __aenter__, __aexit__


TCP implementation
==================

.. autoclass:: AsyncTCPNetworkClient
   :members:

UDP implementation
==================

.. autoclass:: AsyncUDPNetworkClient
   :members:
   :exclude-members: iter_received_packets


Generic UDP endpoint
--------------------

.. autoclass:: AsyncUDPNetworkEndpoint
   :members:
   :special-members: __aenter__, __aexit__
