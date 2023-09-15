***********
Clients API
***********

.. automodule:: easynetwork.api_sync.client

.. contents:: Table of Contents
   :local:

------

Abstract Base Class
===================

.. autoclass:: AbstractNetworkClient
   :members:
   :special-members: __enter__, __exit__

TCP Implementation
==================

.. autoclass:: TCPNetworkClient
   :members:

UDP Implementation
==================

.. autoclass:: UDPNetworkClient
   :members:
   :exclude-members: iter_received_packets


Generic UDP Endpoint
--------------------

.. autoclass:: UDPNetworkEndpoint
   :members:
   :special-members: __enter__, __exit__
