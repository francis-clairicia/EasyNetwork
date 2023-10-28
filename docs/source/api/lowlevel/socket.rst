**************
Socket Helpers
**************

.. automodule:: easynetwork.lowlevel.socket

Data Structures And Constants
=============================

.. autoclass:: SocketAttribute
   :members:

.. autoclass:: INETSocketAttribute
   :members:
   :inherited-members:

.. autoclass:: TLSAttribute
   :members:

.. autoenum:: AddressFamily
   :members:

.. autonamedtuple:: IPv4SocketAddress
   :members:

.. autonamedtuple:: IPv6SocketAddress
   :members:

.. autodata:: SocketAddress
   :annotation: :TypeAlias = IPv4SocketAddress | IPv6SocketAddress


Classes
=======

.. autoprotocol:: SupportsSocketOptions

.. autoprotocol:: ISocket

.. autoclass:: SocketProxy
   :members:


Functions
=========

.. autofunction:: new_socket_address

.. autofunction:: set_tcp_nodelay

.. autofunction:: set_tcp_keepalive

Socket Lingering
----------------

.. autofunction:: get_socket_linger_struct

.. autofunction:: enable_socket_linger

.. autofunction:: disable_socket_linger
