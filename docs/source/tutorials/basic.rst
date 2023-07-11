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

   The main advantage of this model is to declaratively define the communication protocol
   (the name of the class being that of the protocol, the types of objects sent and received, etc.).

   Another advantage is that the serializer (and converter, if any) can be configured in a single place in the project.


Step 2: The server
------------------

Now that we have established the communication protocol, we can create our server.

Create your request handler
^^^^^^^^^^^^^^^^^^^^^^^^^^^

First, you must create a request handler class by subclassing the ``AsyncBaseRequestHandler`` class and overriding its ``handle()`` method;
this method will process incoming requests.

Its ``bad_request()`` method must also be overridden to handle parsing errors.

.. literalinclude:: ../_include/examples/tutorials/basic/server.py
   :lines: 11-26
   :lineno-start: 11

.. note::

   Pay attention to ``handle()``, it is an :std:term:`asynchronous generator` function.

   All requests sent by a client are literally injected into the generator via the ``yield`` statement.

   .. literalinclude:: ../_include/examples/tutorials/basic/server.py
      :lines: 17-18
      :lineno-start: 17
      :emphasize-lines: 2
      :dedent:

.. note::

   Leaving the generator will *not* close the connection, a new generator will be created afterwards.
   You may manually close the connection if you want to::

      await client.aclose()

Start the server
^^^^^^^^^^^^^^^^

Second, you must instantiate one of the server classes, passing it the server's address, the :term:`protocol object` instance, and the request handler instance.

We want a TCP server, so ``StandaloneTCPNetworkServer`` will do the trick.

.. literalinclude:: ../_include/examples/tutorials/basic/server.py
   :lines: 29-
   :lineno-start: 29

.. note::

   Setting ``host`` to ``None`` will bind the server in all interfaces.

Full code
^^^^^^^^^

.. literalinclude:: ../_include/examples/tutorials/basic/server.py
   :linenos:
   :caption: server.py


.. Links

.. _FTP: https://fr.wikipedia.org/wiki/File_Transfer_Protocol
