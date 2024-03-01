***********
Clients API
***********

Asynchronous network client interfaces

.. currentmodule:: easynetwork.clients

.. contents:: Table of Contents
   :local:

------

Abstract Base Class
===================

.. autoclass:: easynetwork.clients.abc::AbstractAsyncNetworkClient
   :members:
   :special-members: __aenter__, __aexit__


TCP Implementation
==================

.. autoclass:: AsyncTCPNetworkClient
   :members:
   :inherited-members:

UDP Implementation
==================

.. autoclass:: AsyncUDPNetworkClient
   :members:
   :inherited-members:
