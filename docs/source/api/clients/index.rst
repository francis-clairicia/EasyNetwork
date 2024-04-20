***********
Clients API
***********

.. automodule:: easynetwork.clients

.. contents:: Table of Contents
   :local:

------

Asynchronous Client Objects (``async def``)
===========================================

Abstract Base Class
-------------------

.. autoclass:: easynetwork.clients.abc::AbstractAsyncNetworkClient
   :members:
   :special-members: __aenter__, __aexit__


TCP Implementation
------------------

.. autoclass:: AsyncTCPNetworkClient
   :members:
   :inherited-members:

UDP Implementation
------------------

.. autoclass:: AsyncUDPNetworkClient
   :members:
   :inherited-members:


Synchronous Client Objects
==========================

Abstract Base Class
-------------------

.. autoclass:: easynetwork.clients.abc::AbstractNetworkClient
   :members:
   :special-members: __enter__, __exit__


TCP Implementation
------------------

.. autoclass:: TCPNetworkClient
   :members:
   :inherited-members:

UDP Implementation
------------------

.. autoclass:: UDPNetworkClient
   :members:
   :inherited-members:
