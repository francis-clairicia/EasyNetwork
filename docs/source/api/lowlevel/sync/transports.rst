***********************
Data Transport Adapters
***********************

.. automodule:: easynetwork.lowlevel.api_sync.transports

.. contents:: Table of Contents
   :local:

------

Abstract Base Classes
=====================

.. automodule:: easynetwork.lowlevel.api_sync.transports.abc
   :members:
   :special-members: __enter__, __exit__


``selectors``-based Transports
==============================

.. automodule:: easynetwork.lowlevel.api_sync.transports.base_selector
   :members:


Composite Data Transports
=========================

.. automodule:: easynetwork.lowlevel.api_sync.transports.composite
   :members:

.. autotypevar:: _T_SendStreamTransport
   :no-index:

.. autotypevar:: _T_ReceiveStreamTransport
   :no-index:

.. autotypevar:: _T_SendDatagramTransport
   :no-index:

.. autotypevar:: _T_ReceiveDatagramTransport
   :no-index:


Socket Transport Implementations
================================

.. automodule:: easynetwork.lowlevel.api_sync.transports.socket
   :members:
