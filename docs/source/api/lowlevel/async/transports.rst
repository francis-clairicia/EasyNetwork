***********************
Data Transport Adapters
***********************

.. automodule:: easynetwork.lowlevel.api_async.transports

.. contents:: Table of Contents
   :local:

------

Abstract Base Classes
=====================

.. automodule:: easynetwork.lowlevel.api_async.transports.abc
   :members:
   :special-members: __aenter__, __aexit__


SSL/TLS Support
===============

.. automodule:: easynetwork.lowlevel.api_async.transports.tls
   :members:


Composite Data Transports
=========================

.. automodule:: easynetwork.lowlevel.api_async.transports.composite
   :members:

.. autotypevar:: _T_SendStreamTransport
   :no-index:

.. autotypevar:: _T_ReceiveStreamTransport
   :no-index:

.. autotypevar:: _T_SendDatagramTransport
   :no-index:

.. autotypevar:: _T_ReceiveDatagramTransport
   :no-index:


Miscellaneous
=============

.. automodule:: easynetwork.lowlevel.api_async.transports.utils
   :members:

.. autoprotocol:: _TransportLike
