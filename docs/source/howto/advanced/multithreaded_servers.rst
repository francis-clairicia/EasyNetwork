**********************************************
How-to — Multithreading Integration In Servers
**********************************************

.. include:: ../../_include/sync-async-variants.rst

.. contents:: Table of Contents
   :local:

------

Run Blocking Functions In A Worker Thread
=========================================

You can run IO-bound functions in another OS thread and :keyword:`await` the result:

.. tabs::

   .. group-tab:: Using ``asyncio``

      .. literalinclude:: ../../_include/examples/howto/multithreading/run_in_thread.py
         :pyobject: RunInSomeThreadRequestHandlerAsyncIO
         :start-after: RunInSomeThreadRequestHandlerAsyncIO
         :dedent:
         :linenos:
         :emphasize-lines: 7

      .. seealso:: The :func:`asyncio.to_thread` coroutine.

   .. group-tab:: Using ``trio``

      .. literalinclude:: ../../_include/examples/howto/multithreading/run_in_thread.py
         :pyobject: RunInSomeThreadRequestHandlerTrio
         :start-after: RunInSomeThreadRequestHandlerTrio
         :dedent:
         :linenos:
         :emphasize-lines: 7

      .. seealso:: The :func:`trio.to_thread.run_sync` coroutine.

   .. group-tab:: Using the ``AsyncBackend`` API

      .. literalinclude:: ../../_include/examples/howto/multithreading/run_in_thread.py
         :pyobject: RunInSomeThreadRequestHandlerWithClientBackend
         :start-after: RunInSomeThreadRequestHandlerWithClientBackend
         :dedent:
         :linenos:
         :emphasize-lines: 7

      .. seealso:: The :meth:`.AsyncBackend.run_in_thread` coroutine.


Use A Custom Thread Pool
------------------------

Instead of using the scheduler's global thread pool, you can (and should) have your own thread pool:

.. literalinclude:: ../../_include/examples/howto/multithreading/run_in_thread.py
   :pyobject: RunInSomeThreadRequestHandlerWithExecutor
   :start-after: RunInSomeThreadRequestHandlerWithExecutor
   :dedent:
   :linenos:
   :emphasize-lines: 6-9,17

.. seealso:: The :class:`.AsyncExecutor` class.

Allow Access To The Scheduler Loop From Within A Thread
=======================================================

There are many ways provided by your :term:`asynchronous framework` to get back from a thread to the scheduler loop.
However, the simplest way is to use the provided :class:`.ThreadsPortal` interface:

.. literalinclude:: ../../_include/examples/howto/multithreading/run_from_thread.py
   :pyobject: BaseRunFromSomeThreadRequestHandler
   :start-after: BaseRunFromSomeThreadRequestHandler
   :dedent:
   :linenos:
   :emphasize-lines: 11-12

Calling asynchronous code from a worker thread
----------------------------------------------

If you need to call a coroutine function from a worker thread, you can do this:

.. literalinclude:: ../../_include/examples/howto/multithreading/run_from_thread.py
   :pyobject: RunCoroutineFromSomeThreadRequestHandler
   :start-after: RunCoroutineFromSomeThreadRequestHandler
   :dedent:
   :linenos:
   :emphasize-lines: 14


Calling synchronous code from a worker thread
----------------------------------------------

Occasionally you may need to call synchronous code in the event loop thread from a worker thread.
Common cases include setting asynchronous events or sending data to a stream. Because these methods aren't thread safe,
you need to arrange them to be called inside the event loop thread using :meth:`~.ThreadsPortal.run_sync`:

.. literalinclude:: ../../_include/examples/howto/multithreading/run_from_thread.py
   :pyobject: RunSyncFromSomeThreadRequestHandler
   :start-after: RunSyncFromSomeThreadRequestHandler
   :dedent:
   :linenos:
   :emphasize-lines: 18

Spawning tasks from worker threads
----------------------------------

When you need to spawn a task to be run in the background, you can do so using :meth:`~.ThreadsPortal.run_coroutine_soon`:

.. literalinclude:: ../../_include/examples/howto/multithreading/run_from_thread.py
   :pyobject: SpawnTaskFromSomeThreadRequestHandler
   :start-after: SpawnTaskFromSomeThreadRequestHandler
   :dedent:
   :linenos:
   :emphasize-lines: 23

Cancelling tasks spawned this way can be done by cancelling the returned :class:`~concurrent.futures.Future`.
