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
