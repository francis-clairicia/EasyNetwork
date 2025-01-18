***********
Clients API
***********

.. automodule:: easynetwork.clients

.. contents:: Table of Contents
   :local:

------

Abstract Base Classes
=====================

.. automodule:: easynetwork.clients.abc
   :members:
   :special-members: __aenter__, __aexit__


Asynchronous Client Objects (``async def``)
===========================================

TCP Implementation
------------------

.. automodule:: easynetwork.clients.async_tcp
   :members:
   :inherited-members:

UDP Implementation
------------------

.. automodule:: easynetwork.clients.async_udp
   :members:
   :inherited-members:

UNIX Stream Implementation
--------------------------

.. automodule:: easynetwork.clients.async_unix_stream
   :members:
   :inherited-members:

UNIX Datagram Implementation
----------------------------

.. automodule:: easynetwork.clients.async_unix_datagram
   :members:
   :inherited-members:


Synchronous Client Objects
==========================

TCP Implementation
------------------

.. automodule:: easynetwork.clients.tcp
   :members:
   :inherited-members:

UDP Implementation
------------------

.. automodule:: easynetwork.clients.udp
   :members:
   :inherited-members:

UNIX Stream Implementation
--------------------------

.. automodule:: easynetwork.clients.unix_stream
   :members:
   :inherited-members:

UNIX Datagram Implementation
----------------------------

.. automodule:: easynetwork.clients.unix_datagram
   :members:
   :inherited-members:

-----

.. seealso::

   :doc:`/howto/tcp_clients`
      Describes what can be done with the clients.

   :doc:`/howto/udp_clients`
      Describes what can be done with the clients.

   :doc:`/alternatives/unix_sockets/unix_stream_clients`
      Describes what can be done with the clients.

   :doc:`/alternatives/unix_sockets/unix_datagram_clients`
      Describes what can be done with the clients.
