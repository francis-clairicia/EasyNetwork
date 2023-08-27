***********
Clients API
***********

.. automodule:: easynetwork.api_sync.client

.. contents:: Table of Contents
   :local:

------

Abstract base class
===================

.. autoclass:: AbstractNetworkClient
   :members:
   :special-members: __enter__, __exit__

TCP implementation
==================

.. autoclass:: TCPNetworkClient
   :members:

UDP implementation
==================

.. autoclass:: UDPNetworkClient
   :members:
   :exclude-members: iter_received_packets


Generic UDP endpoint
--------------------

.. autoclass:: UDPNetworkEndpoint
   :members:
   :special-members: __enter__, __exit__
