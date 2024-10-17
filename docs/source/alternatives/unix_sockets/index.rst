******************************
Alternative — Use Unix Sockets
******************************

Similar to IP connections, EasyNetwork can also be used with UNIX sockets.

.. warning::

   Due to the opaque abstraction of the implementation, not all UNIX socket features are currently available. This will be added in the future.

   Missing features are described in the appropriate sections.

------

.. toctree::
   :maxdepth: 1
   :caption: UNIX Clients

   unix_stream_clients
   unix_datagram_clients

------

.. toctree::
   :maxdepth: 1
   :caption: UNIX Servers

   unix_stream_servers
   unix_datagram_servers
