***************************
How-to — Standalone Servers
***************************

.. include:: ../../_include/sync-async-variants.rst

.. contents:: Table of Contents
   :local:

------

Introduction
============

Standalone servers are classes that can create ready-to-run servers with no predefined asynchronous context
(i.e., no :keyword:`async` / :keyword:`await`). They use (and block) a thread to accept requests,
and their methods are meant to be used by other threads for control (e.g. shutdown).

By default, the runner is ``"asyncio"``, but it can be changed during object creation.


Server Object
=============

.. tabs::

   .. group-tab:: StandaloneTCPNetworkServer

      .. literalinclude:: ../../_include/examples/howto/tcp_servers/standalone/server.py
         :linenos:
         :emphasize-lines: 10,21-26,46-50

   .. group-tab:: StandaloneUDPNetworkServer

      .. literalinclude:: ../../_include/examples/howto/udp_servers/standalone/server.py
         :linenos:
         :emphasize-lines: 10,21-26,46-50


Run Server In Background
------------------------

Unlike asynchronous tasks, it is mandatory to spawn a separate execution thread. :class:`.NetworkServerThread` is useful for this case:

.. tabs::

   .. group-tab:: StandaloneTCPNetworkServer

      .. literalinclude:: ../../_include/examples/howto/tcp_servers/standalone/background_server.py
         :linenos:

   .. group-tab:: StandaloneUDPNetworkServer

      .. literalinclude:: ../../_include/examples/howto/udp_servers/standalone/background_server.py
         :linenos:

The output of the example should look something like this:

.. tabs::

   .. group-tab:: StandaloneTCPNetworkServer

      .. code:: console

         $ python background_server.py
         Server loop running in thread: Thread-1
         From server: {'thread': 'Thread-1', 'task': 'Task-6', 'request': {'message': 'Hello world 1'}}
         From server: {'thread': 'Thread-1', 'task': 'Task-8', 'request': {'message': 'Hello world 2'}}
         From server: {'thread': 'Thread-1', 'task': 'Task-10', 'request': {'message': 'Hello world 3'}}

   .. group-tab:: StandaloneUDPNetworkServer

      .. code:: console

         $ python background_server.py
         Server loop running in thread: Thread-1
         From server: {'thread': 'Thread-1', 'task': 'Task-5', 'request': {'message': 'Hello world 1'}}
         From server: {'thread': 'Thread-1', 'task': 'Task-6', 'request': {'message': 'Hello world 2'}}
         From server: {'thread': 'Thread-1', 'task': 'Task-7', 'request': {'message': 'Hello world 3'}}
