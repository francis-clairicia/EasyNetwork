***********
Servers API
***********

.. automodule:: easynetwork.api_sync.server

.. contents:: Table of Contents
   :local:

------

Abstract base class
===================

.. autoclass:: AbstractNetworkServer
   :members:
   :special-members: __enter__, __exit__

TCP implementation
==================

.. autoclass:: StandaloneTCPNetworkServer
   :inherited-members:
   :members:

UDP implementation
==================

.. autoclass:: StandaloneUDPNetworkServer
   :inherited-members:
   :members:
