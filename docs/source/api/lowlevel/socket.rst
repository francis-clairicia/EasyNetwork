**************
Socket Helpers
**************

.. automodule:: easynetwork.lowlevel.socket

.. contents:: Table of Contents
   :local:

-----

Data Structures And Constants
=============================

Typed Attributes
----------------

.. autoclass:: SocketAttribute
   :members:

.. autoclass:: INETSocketAttribute
   :members:
   :inherited-members:

.. autoclass:: UNIXSocketAttribute
   :members:
   :inherited-members:

.. autoclass:: TLSAttribute
   :members:

Internet addresses
------------------

.. autonamedtuple:: IPv4SocketAddress
   :members:

.. autonamedtuple:: IPv6SocketAddress
   :members:

.. autodata:: SocketAddress
   :annotation: :TypeAlias = IPv4SocketAddress | IPv6SocketAddress

Unix-related
------------

.. autoclass:: UnixSocketAddress
   :members:

   .. describe:: str(addr)

      Displays the Unix address in a similar way to that seen in ``/proc/net/unix``.

      .. versionchanged:: NEXT_VERSION
         Prior to this version, ``str(addr)`` used to return something like ``repr(addr)``.

      .. note::
         Returns ``<unnamed>`` for unnamed addresses.

      .. rubric:: Example

      >>> from easynetwork.lowlevel.socket import UnixSocketAddress
      >>> str(UnixSocketAddress.from_pathname("/tmp/sock"))
      '/tmp/sock'
      >>> str(UnixSocketAddress.from_abstract_name(b"hidden"))
      '@hidden'
      >>> str(UnixSocketAddress()) # Unnamed
      '<unnamed>'

.. autonamedtuple:: UnixCredentials
   :members:


Classes
=======

.. autoprotocol:: SupportsSocketOptions

.. autoprotocol:: ISocket

.. autoclass:: SocketProxy
   :members:


Functions
=========

Internet addresses
------------------

.. autofunction:: new_socket_address

TCP Options
-----------

.. autofunction:: set_tcp_nodelay

.. autofunction:: set_tcp_keepalive

Socket Lingering
----------------

.. autonamedtuple:: socket_linger
   :members:

.. autofunction:: get_socket_linger_struct

.. autofunction:: get_socket_linger

.. autofunction:: enable_socket_linger

.. autofunction:: disable_socket_linger
