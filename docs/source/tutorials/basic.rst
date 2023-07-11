.. highlight:: python

Basic tutorial - An echo client/server over TCP
===============================================

.. include:: ../_include/sync-async-variants.rst


Goal
----

To see how to create a server and a client with the minimum requirements,
let's create a server that will return everything sent by a connected client.


Step 1: The :term:`communication protocol`
------------------------------------------

Before doing all this networking stuff, you need to know what you want to transmit and in what format.

Choose the :term:`serializer`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

There is a bunch of serializers available in ``easynetwork.serializers`` for everyone to enjoy:

* ``JSONSerializer``: an :term:`incremental serializer` using the :py:mod:`json` module.

* ``PickleSerializer``: a :term:`one-shot serializer` using the :py:mod:`pickle` module.

* ``StringLineSerializer``: an :term:`incremental serializer` for communication based on ASCII character strings (e.g. `FTP`_).

* etc.

For the tutorial, ``JSONSerializer`` will be used.

.. todo::

   * Add cross-references

   * Link to all the available serializer


Build your :term:`protocol object`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

For communication via TCP, a ``StreamProtocol`` object must be created.

.. literalinclude:: ../_include/examples/tutorials/basic/json_protocol.py
   :linenos:
   :caption: json_protocol.py

.. note::

   Of course, you are under no obligation to create a subclass.

   The main advantage of this model is to declaratively define the :term:`communication protocol`
   (the name of the class being that of the protocol, the types of objects sent and received, etc.).

   Another advantage is that the :term:`serializer` (and :term:`converter`, if any) can be configured in a single place in the project.


Step 2: The server
------------------

Now that we have established the :term:`communication protocol`, we can create our server.

Create your request handler
^^^^^^^^^^^^^^^^^^^^^^^^^^^

First, you must create a request handler class by subclassing the ``AsyncBaseRequestHandler`` class and overriding its ``handle()`` method;
this method will process incoming requests.

Its ``bad_request()`` method must also be overridden to handle parsing errors.

.. literalinclude:: ../_include/examples/tutorials/basic/echo_request_handler.py
   :linenos:
   :caption: echo_request_handler.py

.. note::

   Pay attention to ``handle()``, it is an :std:term:`asynchronous generator` function.

   All requests sent by a client are literally injected into the generator via the :ref:`yield <yield>` statement.

   .. literalinclude:: ../_include/examples/tutorials/basic/echo_request_handler.py
      :lines: 15-16
      :lineno-start: 15
      :emphasize-lines: 2
      :dedent:

   You can ``yield`` several times if you want to wait for a new packet from the client in the same context.

.. warning::

   Leaving the generator will *not* close the connection, a new generator will be created afterwards.
   You may, however, explicitly close the connection if you want to::

      await client.aclose()

Start the server
^^^^^^^^^^^^^^^^

Second, you must instantiate the TCP server class, passing it the server's address, the :term:`protocol object` instance,
and the request handler instance.

.. tabs::

   .. group-tab:: Synchronous

      .. literalinclude:: ../_include/examples/tutorials/basic/server.py
         :linenos:
         :caption: server.py

   .. group-tab:: Asynchronous

      .. literalinclude:: ../_include/examples/tutorials/basic/async_server.py
         :linenos:
         :caption: async_server.py

.. note::

   Setting ``host`` to ``None`` will bind the server in all interfaces.

.. Links

.. _FTP: https://fr.wikipedia.org/wiki/File_Transfer_Protocol
