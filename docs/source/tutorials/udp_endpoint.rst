.. highlight:: python

Create a UDP endpoint
=====================

This tutorial will show you how to create a ready-to-use datagram endpoint over UDP.

.. include:: ../_include/sync-async-variants.rst

The :term:`communication protocol`
----------------------------------

You will need a :term:`protocol object`, as for the :ref:`echo client/server over TCP <echo-client-server-tcp-protocol>`.

For the tutorial, ``JSONSerializer`` will also be used.

For communication via UDP, a ``DatagramProtocol`` object must be created this time.

.. literalinclude:: ../_include/examples/tutorials/udp_endpoint/json_protocol.py
   :linenos:
   :caption: json_protocol.py
   :emphasize-lines: 5,14


The UDP endpoint
----------------

Here is an example of how to use a UDP endpoint:

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../_include/examples/tutorials/udp_endpoint/endpoint.py
         :linenos:
         :caption: endpoint.py

   .. group-tab:: Asynchronous

      .. literalinclude:: ../_include/examples/tutorials/udp_endpoint/async_endpoint.py
         :linenos:
         :caption: endpoint.py

The output of the example should look something like this:

Receiver:

.. code-block:: console

   (.venv) $ python endpoint.py receiver
   Receiver available on port 58456
   127.0.0.1:35985 sent {'command-line arguments': ['Hello', 'world!']}


Sender:

.. code-block:: console

   (.venv) $ python endpoint.py sender "127.0.0.1:58456" Hello world!
   Sent to 127.0.0.1:58456       : {'command-line arguments': ['Hello', 'world!']}
   Received from 127.0.0.1:58456 : {'command-line arguments': ['Hello', 'world!']}
