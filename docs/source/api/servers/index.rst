***********
Servers API
***********

.. automodule:: easynetwork.servers

.. contents:: Table of Contents
   :local:

------

Abstract Base Classes
=====================

.. automodule:: easynetwork.servers.abc
   :members:
   :special-members: __aenter__, __aexit__


Asynchronous Server Objects (``async def``)
===========================================

TCP Implementation
------------------

.. automodule:: easynetwork.servers.async_tcp
   :members:
   :inherited-members:

UDP Implementation
------------------

.. automodule:: easynetwork.servers.async_udp
   :members:
   :inherited-members:

UNIX Stream Implementation
--------------------------

.. automodule:: easynetwork.servers.async_unix_stream
   :members:
   :inherited-members:

UNIX Datagram Implementation
----------------------------

.. automodule:: easynetwork.servers.async_unix_datagram
   :members:
   :inherited-members:


Synchronous Server Objects
==========================

TCP Implementation
------------------

.. automodule:: easynetwork.servers.standalone_tcp
   :members:
   :inherited-members:

UDP Implementation
------------------

.. automodule:: easynetwork.servers.standalone_udp
   :members:
   :inherited-members:

UNIX Stream Implementation
--------------------------

.. automodule:: easynetwork.servers.standalone_unix_stream
   :members:
   :inherited-members:

UNIX Datagram Implementation
----------------------------

.. automodule:: easynetwork.servers.standalone_unix_datagram
   :members:
   :inherited-members:


Request Handler Interface
=========================

.. automodule:: easynetwork.servers.handlers

.. autoclass:: AsyncStreamRequestHandler
   :members:

.. autoclass:: AsyncDatagramRequestHandler
   :members:

Client API
----------

.. autoclass:: AsyncBaseClientInterface
   :members:

.. autoclass:: AsyncStreamClient
   :members:

.. autoclass:: AsyncDatagramClient
   :members:
   :special-members: __eq__, __hash__


Client Attributes
-----------------

.. autoclass:: INETClientAttribute
   :members:

.. autoclass:: UNIXClientAttribute
   :members:


------

Server implementation tools
===========================

.. toctree::
   :maxdepth: 1

   threads_helper
   misc

-----

.. seealso::

   :doc:`/howto/advanced/standalone_servers`
      Explains the case of stand-alone servers.

   :doc:`/howto/tcp_servers`
      Describes what can be done with the servers.

   :doc:`/howto/udp_servers`
      Describes what can be done with the servers.

   :doc:`/alternatives/unix_sockets/unix_stream_servers`
      Describes what can be done with the servers.

   :doc:`/alternatives/unix_sockets/unix_datagram_servers`
      Describes what can be done with the servers.
