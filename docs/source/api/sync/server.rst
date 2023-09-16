***********
Servers API
***********

.. automodule:: easynetwork.api_sync.server

.. contents:: Table of Contents
   :local:

------

Abstract Base Class
===================

.. autoclass:: AbstractNetworkServer
   :members:
   :special-members: __enter__, __exit__

TCP Implementation
==================

.. autoclass:: StandaloneTCPNetworkServer
   :inherited-members:
   :members:

UDP Implementation
==================

.. autoclass:: StandaloneUDPNetworkServer
   :inherited-members:
   :members:
