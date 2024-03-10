***********
Servers API
***********

Network server interfaces

.. currentmodule:: easynetwork.servers

.. contents:: Table of Contents
   :local:

------

Abstract Base Class
===================

.. autoclass:: easynetwork.servers.abc::AbstractNetworkServer
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
