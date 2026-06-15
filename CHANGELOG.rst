*********
Changelog
*********

All notable changes to this project will be documented in this file.

The format is based on `Keep a Changelog <https://keepachangelog.com/en/1.1.0/>`_,
and this project adheres to `Semantic Versioning <https://semver.org/spec/v2.0.0.html>`_.

See also the `Release Notes <https://github.com/francis-clairicia/EasyNetwork/releases>`_.

To see unreleased changes, please see the `CHANGELOG on the main branch documentation <https://easynetwork.readthedocs.io/en/latest/changelog.html>`_.

.. towncrier release notes start

`1.2.0 <https://github.com/francis-clairicia/EasyNetwork/compare/1.1.4...1.2.0>`_ (2026-02-08)
==============================================================================================

Packaging
---------

- Bumped minimum version of ``hatchling`` build dependency to **1.27**. (`#414 <https://github.com/francis-clairicia/EasyNetwork/pull/414>`_)
- Updated project metadata to include SPDX license expression. The project is now compliant with the :pep:`639`. (`#414 <https://github.com/francis-clairicia/EasyNetwork/pull/414>`_)
- Explicitly declare support of tested BSD plaforms. (`#429 <https://github.com/francis-clairicia/EasyNetwork/pull/429>`_)
- Added support of Python 3.14. (`#440 <https://github.com/francis-clairicia/EasyNetwork/pull/440>`_)


Added
-----

- Added Unix Socket's control messages support on Linux, MacOS and BSD-related platforms:

  * ``UnixStreamClient`` and ``AsyncUnixStreamClient``:

     * ``send_packet()``: Added ``ancillary_data`` parameter.

     * ``recv_packet()``: Added ``ancillary_data`` and ``ancillary_bufsize`` parameters.

  * ``UnixDatagramClient`` and ``AsyncUnixDatagramClient``:

     * ``send_packet()``: Added ``ancillary_data`` parameter.

     * ``recv_packet()``: Added ``ancillary_data`` and ``ancillary_bufsize`` parameters.

  * ``StandaloneUnixStreamServer`` and ``AsyncUnixStreamServer``:

     * Added ``ancillary_bufsize`` parameter.

  * ``StandaloneUnixDatagramServer`` and ``AsyncUnixDatagramServer``:

     * Added ``receive_ancillary_data`` and ``ancillary_bufsize`` parameters.

  * Request handlers:

     * ``AsyncStreamRequestHandler``: ``handle()`` and ``on_connection()`` may ``yield`` the new ``RecvParams`` object.

     * ``AsyncDatagramRequestHandler``: ``handle()`` may ``yield`` the new ``RecvParams`` object.

     * Added ``AsyncStreamClient.send_packet_with_ancillary()``.

     * Added ``AsyncDatagramClient.send_packet_with_ancillary()``.

  * Low-level API:

     * In ``easynetwork.lowlevel.socket`` module:

        * Added ``SocketAncillary`` container which handles ``SCMRights`` and ``SCMCredentials`` messages if available on current platform.

     * In ``easynetwork.lowlevel.request_handler`` module:

        * Added ``RecvParams`` and ``RecvAncillaryDataParams``, used by request handlers.

     * Asynchronous API:

        * In ``easynetwork.lowlevel.api_async.transports`` package:

           * Added ``AsyncStreamReadTransport.recv_with_ancillary()``.

           * Added ``AsyncStreamReadTransport.recv_with_ancillary_into()``.

           * Added ``AsyncStreamWriteTransport.send_all_with_ancillary()``.

           * Added ``AsyncDatagramReadTransport.recv_with_ancillary()``.

           * Added ``AsyncDatagramWriteTransport.send_with_ancillary()``.

           * Added ``AsyncDatagramListener.serve_with_ancillary()``.

           * Added ``AsyncDatagramListener.send_with_ancillary_to()``.

        * In ``easynetwork.lowlevel.api_async.endpoints`` package:

           * Added ``AsyncStreamReceiverEndpoint.recv_packet_with_ancillary()``.

           * Added ``AsyncStreamSenderEndpoint.send_packet_with_ancillary()``.

           * Added ``AsyncStreamEndpoint.recv_packet_with_ancillary()``.

           * Added ``AsyncStreamEndpoint.send_packet_with_ancillary()``.

           * Added ``AsyncDatagramReceiverEndpoint.recv_packet_with_ancillary()``.

           * Added ``AsyncDatagramSenderEndpoint.send_packet_with_ancillary()``.

           * Added ``AsyncDatagramEndpoint.recv_packet_with_ancillary()``.

           * Added ``AsyncDatagramEndpoint.send_packet_with_ancillary()``.

        * In ``easynetwork.lowlevel.api_async.servers`` package:

           * Added ``ConnectedStreamClient.send_packet_with_ancillary()``.

           * ``AsyncStreamServer.serve()``: Generators returned by ``client_connected_cb`` may ``yield`` the new ``RecvParams`` object.

           * ``AsyncStreamServer.serve()``: Added ``ancillary_bufsize`` parameter.

           * Added ``AsyncDatagramServer.send_packet_with_ancillary_to()``.

           * Added ``AsyncDatagramServer.serve_with_ancillary()``.

           * ``AsyncDatagramServer.serve()``: Generators returned by ``datagram_received_cb`` may ``yield`` the new ``RecvParams`` object.

     * Synchronous (blocking) API:

        * In ``easynetwork.lowlevel.api_sync.transports`` package:

           * Added ``StreamReadTransport.recv_with_ancillary()``.

           * Added ``StreamReadTransport.recv_with_ancillary_into()``.

           * Added ``StreamWriteTransport.send_all_with_ancillary()``.

           * Added ``DatagramReadTransport.recv_with_ancillary()``.

           * Added ``DatagramWriteTransport.send_with_ancillary()``.

        * In ``easynetwork.lowlevel.api_sync.endpoints`` package:

           * Added ``StreamReceiverEndpoint.recv_packet_with_ancillary()``.

           * Added ``StreamSenderEndpoint.send_packet_with_ancillary()``.

           * Added ``StreamEndpoint.recv_packet_with_ancillary()``.

           * Added ``StreamEndpoint.send_packet_with_ancillary()``.

           * Added ``DatagramReceiverEndpoint.recv_packet_with_ancillary()``.

           * Added ``DatagramSenderEndpoint.send_packet_with_ancillary()``.

           * Added ``DatagramEndpoint.recv_packet_with_ancillary()``.

           * Added ``DatagramEndpoint.send_packet_with_ancillary()``.

  GitHub PR: (`#441 <https://github.com/francis-clairicia/EasyNetwork/pull/441>`_)


Changed
-------

- ``UnixSocketAddress`` now displays the Unix address in a similar way to that seen in ``/proc/net/unix``. (`#416 <https://github.com/francis-clairicia/EasyNetwork/pull/416>`_)
- ``AsyncUnixStreamServer`` and ``AsyncUnixDatagramServer``: There is a more explicit error message when the current platform
  does not support automatic socket binding. (`#419 <https://github.com/francis-clairicia/EasyNetwork/pull/419>`_)
- Low-level API: ``trio``: The ``TaskGroup`` context manager raises a single ``trio.Cancelled`` error when all the tasks has ben cancelled
  instead of an ``ExceptionGroup``. This is already the behavior with ``asyncio``. (`#426 <https://github.com/francis-clairicia/EasyNetwork/pull/426>`_)


Fixed
-----

- Fixed connection errors not caught by ``AsyncTCPNetworkClient`` and ``AsyncUnixStreamClient`` if the object is closed in a concurrent task.
  From now on, a ``ClientClosedError`` is raised in such case. (`#424 <https://github.com/francis-clairicia/EasyNetwork/pull/424>`_)
- Low-level API: ``asyncio``: Fixed ``AsyncDatagramTransport`` and ``AsyncDatagramListener`` raising an ``OSError`` with ``errno.ECONNABORTED``
  instead of ``errno.EBADF`` when the transport has been closed. (`#424 <https://github.com/francis-clairicia/EasyNetwork/pull/424>`_)
- Low-level API: ``trio``: Fixed ``trio.ClosedResourceError`` not caught by :

  * ``AsyncStreamTransport.recv_into()``

  * ``AsyncStreamTransport.send_all_from_iterable()``

  * ``AsyncDatagramTransport.recv()``

  * ``AsyncDatagramTransport.send()``

  * ``AsyncDatagramListener.serve()``

  * ``AsyncDatagramListener.send_to()``

  This exception is now transformed to the corresponding ``OSError``. (`#426 <https://github.com/francis-clairicia/EasyNetwork/pull/426>`_)
- Low-level API: ``asyncio``: Fixed performance issues in ``CancelScope``. (`#430 <https://github.com/francis-clairicia/EasyNetwork/pull/430>`_)


Deprecated
----------

- Request handlers which ``yield`` a number (for the timeout) will emit a ``DeprecationWarning``. This affects:

  * Requests handlers :

     * ``AsyncStreamRequestHandler.handle()``

     * ``AsyncStreamRequestHandler.on_connection()``

     * ``AsyncDatagramRequestHandler.handle()``

  * Low-level API:

     * ``AsyncStreamServer.serve()``: Generators returned by ``client_connected_cb``.

     * ``AsyncDatagramServer.serve()``: Generators returned by ``datagram_received_cb``.

     * ``AsyncDatagramServer.serve_with_ancillary()``: Generators returned by ``datagram_received_cb``.

  Use ``easynetwork.lowlevel.request_handler.RecvParams`` instead. (`#441 <https://github.com/francis-clairicia/EasyNetwork/pull/441>`_)


Removed
-------

- The following list :

  * ``UnixStreamClient`` and ``AsyncUnixStreamClient``

  * ``UnixDatagramClient`` and ``AsyncUnixDatagramClient``

  * ``StandaloneUnixStreamServer`` and ``AsyncUnixStreamServer``

  * ``StandaloneUnixDatagramServer`` and ``AsyncUnixDatagramServer``

  * In ``easynetwork.servers.handlers``:

     * ``UNIXClientAttribute``

  * In ``easynetwork.lowlevel.socket``:

     * ``UnixSocketAddress``

     * ``UnixCredentials``

  is no longer available on unsupported platforms (e.g. Windows). (`#417 <https://github.com/francis-clairicia/EasyNetwork/pull/417>`_)
- ``UnixSocketAddress.from_abstract_name()`` and ``UnixSocketAddress.as_abstract_name()`` are no longer available on unsupported platforms (e.g. MacOS). (`#419 <https://github.com/francis-clairicia/EasyNetwork/pull/419>`_)


Documentation
-------------

- ``NEXT_VERSION`` special value can be used in docstrings and documentation and will be replaced when releasing a new version. (`#416 <https://github.com/francis-clairicia/EasyNetwork/pull/416>`_)
- Missing "default" note for ``log_client_connection`` parameter of ``AsyncTCPNetworkServer`` and ``AsyncUnixStreamServer``. (`#418 <https://github.com/francis-clairicia/EasyNetwork/pull/418>`_)


`1.1.4 <https://github.com/francis-clairicia/EasyNetwork/compare/1.1.3...1.1.4>`_ (2025-07-29)
==============================================================================================

Fixed
-----

- Fixed data loss when ``StreamProtocol.build_packet_from_chunks()`` raises an exception before the first ``yield`` statement. (`#413 <https://github.com/francis-clairicia/EasyNetwork/pull/413>`_)


`1.1.3 <https://github.com/francis-clairicia/EasyNetwork/compare/1.1.2...1.1.3>`_ (2025-05-24)
==============================================================================================

Changed
-------

- Improved buffer management when using ``BufferedStreamProtocol``. (`#402 <https://github.com/francis-clairicia/EasyNetwork/pull/402>`_)
- Low-level API: ``AsyncStreamServer.serve()`` and ``AsyncDatagramServer.serve()`` now check the timeout value sent by request handlers. (`#405 <https://github.com/francis-clairicia/EasyNetwork/pull/405>`_)


Fixed
-----

- Low-level API: Fixed ``AsyncStreamServer.serve()`` aborting client connection on regular request handler stop. (`#403 <https://github.com/francis-clairicia/EasyNetwork/pull/403>`_)
- Low-level API: Fixed ``AsyncDatagramServer.serve()`` crash on shut down when there are queued datagrams. (`#407 <https://github.com/francis-clairicia/EasyNetwork/pull/407>`_)


Documentation
-------------

- Fixed missing warning for client's ``aclose()`` methods. (`#404 <https://github.com/francis-clairicia/EasyNetwork/pull/404>`_)


`1.1.2 <https://github.com/francis-clairicia/EasyNetwork/compare/1.1.1...1.1.2>`_ (2025-03-16)
==============================================================================================

Changed
-------

- Miscellaneous internal changes. (`#392 <https://github.com/francis-clairicia/EasyNetwork/pull/392>`_)
- Improved handling of asynchronous generators. (`#393 <https://github.com/francis-clairicia/EasyNetwork/pull/393>`_)
- Low-level API: ``asyncio`` and ``trio``: The ``TaskGroup`` no longer wrap single exception raised within context in an ``ExceptionGroup``. (`#398 <https://github.com/francis-clairicia/EasyNetwork/pull/398>`_)
- Low-level API: ``asyncio``: Optimized ``AsyncListener.serve()`` coroutine by using ``asyncio.AbstractEventLoop.add_reader()`` if available.
  The task is more efficient with event loops based on file descriptor polling. (`#398 <https://github.com/francis-clairicia/EasyNetwork/pull/398>`_)


Fixed
-----

- Low-level API: ``asyncio``: The ``AsyncListener.serve()`` coroutine no longer emits log connection errors
  for direct subclasses of the ``BaseException`` class. (`#392 <https://github.com/francis-clairicia/EasyNetwork/pull/392>`_)
- Low-level API: ``asyncio``: Fixed backend's ``CancelScope`` not catching re-raised exceptions. (`#395 <https://github.com/francis-clairicia/EasyNetwork/pull/395>`_)
- Low-level API: ``asyncio``: Fixed backend's ``CancelScope`` swallowing exceptions by mistake. (`#397 <https://github.com/francis-clairicia/EasyNetwork/pull/397>`_)
- ``AsyncUDPNetworkServer``: On server shut down, the datagram socket reading task is stopped before client tasks.
  This fixes a race condition where the socket was ready for reading a new datagram but the task group has been closed. (`#398 <https://github.com/francis-clairicia/EasyNetwork/pull/398>`_)
- Low-level API: ``asyncio``: Fixed ``TaskGroup.start()`` and ``TaskGroup.start_soon()`` leaving a coroutine object unclosed on ``RuntimeError``. (`#398 <https://github.com/francis-clairicia/EasyNetwork/pull/398>`_)
- ``AsyncTCPNetworkServer``: On server shut down, the socket listeners are stopped before client tasks.
  This fixes a race condition where the socket was ready to accept a new client but the task group has been closed. (`#398 <https://github.com/francis-clairicia/EasyNetwork/pull/398>`_)
- Low-level API: Fixed ``AsyncStreamServer.serve()`` and ``AsyncDatagramServer.serve()`` shutting down when an exception is thrown. (`#399 <https://github.com/francis-clairicia/EasyNetwork/pull/399>`_)


`1.1.1 <https://github.com/francis-clairicia/EasyNetwork/compare/1.1.0...1.1.1>`_ (2025-01-25)
==============================================================================================

Changed
-------

- ``StringLineSerializer.serialize()`` and ``StringLineSerializer.incremental_serialize()`` delegates ``str`` check to ``bytes`` constructor. (`#391 <https://github.com/francis-clairicia/EasyNetwork/pull/391>`_)
- Using a ``JSONSerializer`` with ``use_lines=False`` option, optimized ``incremental_deserialize()`` by 75%. (`#391 <https://github.com/francis-clairicia/EasyNetwork/pull/391>`_)


`1.1.0 <https://github.com/francis-clairicia/EasyNetwork/compare/1.0.0...1.1.0>`_ (2025-01-19)
==============================================================================================

Packaging
---------

- Added support of Python 3.13. (`#361 <https://github.com/francis-clairicia/EasyNetwork/pull/361>`_)
- The CI files (``.github`` folder and ``.readthedocs.yaml``) are now included in the source distribution. (`#384 <https://github.com/francis-clairicia/EasyNetwork/pull/384>`_)
- Bumped minimum version of ``hatchling`` build dependency to **1.26.3**. (`#384 <https://github.com/francis-clairicia/EasyNetwork/pull/384>`_)
- The project now uses the :pep:`735` — Dependency Groups in ``pyproject.toml``. (`#390 <https://github.com/francis-clairicia/EasyNetwork/pull/390>`_)


Dependency changes
------------------

- Bumped minimum version of ``msgpack`` dependency to **1.1.0**. (`#357 <https://github.com/francis-clairicia/EasyNetwork/pull/357>`_)


Added
-----

- Low-level API: Added ``AsyncBackend.create_fair_lock()`` method.
  There is a library-agnostic default implementation that uses ``Event`` objects. (`#348 <https://github.com/francis-clairicia/EasyNetwork/pull/348>`_)
- Low-level API: Added ``StapledStreamTransport`` and ``AsyncStapledStreamTransport`` classes. (`#352 <https://github.com/francis-clairicia/EasyNetwork/pull/352>`_)
- Low-level API: Added ``StapledDatagramTransport`` and ``AsyncStapledDatagramTransport`` classes. (`#352 <https://github.com/francis-clairicia/EasyNetwork/pull/352>`_)
- Low-level API: ``build_lowlevel_stream_server_handler``: Added variadic arguments for ``initializer`` parameter. (`#356 <https://github.com/francis-clairicia/EasyNetwork/pull/356>`_)
- Low-level API: ``build_lowlevel_datagram_server_handler``: Added variadic arguments for ``initializer`` parameter. (`#356 <https://github.com/francis-clairicia/EasyNetwork/pull/356>`_)
- Low-level API: ``AsyncTLSListener``: Added ``handshake_error_handler`` parameter. (`#360 <https://github.com/francis-clairicia/EasyNetwork/pull/360>`_)
- Added Unix Sockets support:

  * Added ``UnixStreamClient`` and ``AsyncUnixStreamClient``.

  * Added ``UnixDatagramClient`` and ``AsyncUnixDatagramClient``.

  * Added ``StandaloneUnixStreamServer`` and ``AsyncUnixStreamServer``.

  * Added ``StandaloneUnixDatagramServer`` and ``AsyncUnixDatagramServer``.

  * Request handlers: Added ``UNIXClientAttribute`` typed attribute set.

  * Low-level API:

     * In ``easynetwork.lowlevel.socket`` module:

        * Added ``UNIXSocketAttribute`` typed attributes set.

        * Added ``UnixCredentials``.

        * Added ``UnixSocketAddress``.

     * In ``easynetwork.lowlevel.api_async.backend`` module:

        * Added ``AsyncBackend.create_unix_stream_connection()``.

        * Added ``AsyncBackend.create_unix_datagram_endpoint()``.

        * Added ``AsyncBackend.create_unix_stream_listener()``.

        * Added ``AsyncBackend.create_unix_datagram_listener()``.

  GitHub PR: (`#389 <https://github.com/francis-clairicia/EasyNetwork/pull/389>`_)


Changed
-------

- ``AsyncTCPNetworkServer``: Concurrently calling ``client.send_packet()`` now ensures that packets are sent in a deterministic order,
  i.e. the task which has been waiting longest. (`#348 <https://github.com/francis-clairicia/EasyNetwork/pull/348>`_)
- Concurrently calling ``AsyncUPNetworkClient.send_packet()`` now ensures that packets are sent in a deterministic order,
  i.e. the task which has been waiting longest. (`#348 <https://github.com/francis-clairicia/EasyNetwork/pull/348>`_)
- Concurrently calling ``AsyncTCPNetworkClient.send_packet()`` now ensures that packets are sent in a deterministic order,
  i.e. the task which has been waiting longest. (`#348 <https://github.com/francis-clairicia/EasyNetwork/pull/348>`_)
- Low-level API: ``trio``: Improved ``AsyncDatagramListener.serve()`` performances. (`#349 <https://github.com/francis-clairicia/EasyNetwork/pull/349>`_)
- Low-level API: ``aclose_forcefully`` now takes any closeable object with a ``backend()`` method. (`#350 <https://github.com/francis-clairicia/EasyNetwork/pull/350>`_)
- Low-level API: ``trio``: Better way to connect a socket. (`#353 <https://github.com/francis-clairicia/EasyNetwork/pull/353>`_)
- ``AsyncUDPNetworkServer``: Introduced a proper client cache system. (`#356 <https://github.com/francis-clairicia/EasyNetwork/pull/356>`_)
- ``AsyncTCPNetworkServer``: When using SSL, handshake timeouts are not logged anymore. (`#360 <https://github.com/francis-clairicia/EasyNetwork/pull/360>`_)
- ``AsyncTCPNetworkServer``: When using SSL, an error on handshake phase is now logged at ``WARNING`` level instead of ``ERROR`` level. (`#360 <https://github.com/francis-clairicia/EasyNetwork/pull/360>`_)
- Low-level API: Faster access to extra attributes. (`#362 <https://github.com/francis-clairicia/EasyNetwork/pull/362>`_)
- Low-level API: ``asyncio``: Improved ``AsyncStreamReadTransport.recv_into()`` performances. (`#385 <https://github.com/francis-clairicia/EasyNetwork/pull/385>`_)
- Low-level API: ``asyncio``: Clear traceback frames of exception objects saved by transports. (`#385 <https://github.com/francis-clairicia/EasyNetwork/pull/385>`_)


Fixed
-----

- Low-level API: ``asyncio``: Fixed TCP socket listener's ``accept()`` not cancelled if the coroutine handles capacity errors. (`#346 <https://github.com/francis-clairicia/EasyNetwork/pull/346>`_)
- Low-level API: ``trio``: The TCP socket listener now handles :manpage:`accept(2)` capacity errors. (`#347 <https://github.com/francis-clairicia/EasyNetwork/pull/347>`_)
- Low-level API: ``trio``: Fixed potential crash when calling concurrently ``AsyncDatagramListener.send_to()`` and ``socket.sendto()`` would block. (`#348 <https://github.com/francis-clairicia/EasyNetwork/pull/348>`_)
- Low-level API: ``AsyncStreamServer``: Pending client data to read was cleared when explicitly closing the client object.
  Now it is done only when the client task is finished. (`#350 <https://github.com/francis-clairicia/EasyNetwork/pull/350>`_)
- Low-level API: ``AsyncTLSStreamTransport``: There was no task synchronization ( locks ) on read and write operations. (`#350 <https://github.com/francis-clairicia/EasyNetwork/pull/350>`_)
- Low-level API: ``trio``: When closing an UDP socket listener, it now waits for all pending datagram to be sent beforre closing the socket. (`#350 <https://github.com/francis-clairicia/EasyNetwork/pull/350>`_)
- ``AsyncTCPNetworkServer``: Clients was not closed when ``aclose()`` coroutine has been cancelled. (`#350 <https://github.com/francis-clairicia/EasyNetwork/pull/350>`_)
- Fixed ``UDPNetworkClient`` trying to bind sockets when it is not needed. (`#354 <https://github.com/francis-clairicia/EasyNetwork/pull/354>`_)
- Fixed ``AsyncUDPNetworkClient`` trying to bind sockets when it is not needed. (`#354 <https://github.com/francis-clairicia/EasyNetwork/pull/354>`_)
- ``AsyncUDPNetworkServer``: Fixed slow access to the client's extra attributes provided. (`#355 <https://github.com/francis-clairicia/EasyNetwork/pull/355>`_)
- ``AsyncTCPNetworkServer``: Fixed slow access to the client's extra attributes provided. (`#355 <https://github.com/francis-clairicia/EasyNetwork/pull/355>`_)
- Low-level API: ``AsyncDatagramServer``: Fixed cache inconsistency. (`#356 <https://github.com/francis-clairicia/EasyNetwork/pull/356>`_)
- ``AsyncTCPNetworkServer``: When using SSL, connection errors during handshake phase do not produce a traceback log. (`#360 <https://github.com/francis-clairicia/EasyNetwork/pull/360>`_)
- Fixed ``AsyncTCPNetworkServer`` stopping the main task because of ``socket.accept()`` raising ignorable errors. (`#367 <https://github.com/francis-clairicia/EasyNetwork/pull/367>`_)
- Low-level API: ``trio``: Fixed UDP socket listener crashing down application on ``socket.recvfrom()`` errors. (`#371 <https://github.com/francis-clairicia/EasyNetwork/pull/371>`_)
- Fixed ``AsyncTCPNetworkClient`` crash with ``ssl=True`` and OpenSSL version before 3.0. (`#381 <https://github.com/francis-clairicia/EasyNetwork/pull/381>`_)
- Fixed ``TCPNetworkClient`` crash with ``ssl=True`` and OpenSSL version before 3.0. (`#381 <https://github.com/francis-clairicia/EasyNetwork/pull/381>`_)
- Low-level API: ``AsyncStreamEndpoint``: Fixed byte buffers not deallocated until garbage collection
  if ``transport.aclose()`` raises an exception. (`#385 <https://github.com/francis-clairicia/EasyNetwork/pull/385>`_)
- Low-level API: ``StreamEndpoint``: Fixed byte buffers not deallocated until garbage collection
  if ``transport.close()`` or ``transport.aclose()`` raises an exception. (`#385 <https://github.com/francis-clairicia/EasyNetwork/pull/385>`_)
- Low-level API: ``StreamReceiverEndpoint``: Fixed byte buffers not deallocated until garbage collection
  if ``transport.close()`` raises an exception. (`#385 <https://github.com/francis-clairicia/EasyNetwork/pull/385>`_)
- Low-level API: ``AsyncStreamReceiverEndpoint``: Fixed byte buffers not deallocated until garbage collection
  if ``transport.aclose()`` raises an exception. (`#385 <https://github.com/francis-clairicia/EasyNetwork/pull/385>`_)
- ``AsyncTCPNetworkClient`` objects was not closed when ``aclose()`` coroutine has been cancelled. (`#389 <https://github.com/francis-clairicia/EasyNetwork/pull/389>`_)
- ``AsyncUDPNetworkClient`` objects was not closed when ``aclose()`` coroutine has been cancelled. (`#389 <https://github.com/francis-clairicia/EasyNetwork/pull/389>`_)


Removed
-------

- Removed ``max_recv_size`` property from high-level API:

  * ``AsyncTCPNetworkClient``

  * ``TCPNetworkClient``

  The returned value was not reliable. (`#350 <https://github.com/francis-clairicia/EasyNetwork/pull/350>`_)
- Removed ``max_recv_size`` property from low-level API:

  * Asynchronous API:

     * ``AsyncStreamReceiverEndpoint``

     * ``AsyncStreamEndpoint``

  * Blocking API:

     * ``StreamReceiverEndpoint``

     * ``StreamEndpoint``

  The returned value was not reliable. (`#350 <https://github.com/francis-clairicia/EasyNetwork/pull/350>`_)


Documentation
-------------

- Build: Bumped minimum version of ``sphinx`` dependency to **8.1**. (`#359 <https://github.com/francis-clairicia/EasyNetwork/pull/359>`_)
- Build: Bumped minimum version of ``sphinx-rtd-theme`` dependency to **3.0**. (`#359 <https://github.com/francis-clairicia/EasyNetwork/pull/359>`_)
- Fixed missing documentation on socket addresses and client attributes. (`#374 <https://github.com/francis-clairicia/EasyNetwork/pull/374>`_)
- Removed ``reuse_port`` option from UDP clients. (`#375 <https://github.com/francis-clairicia/EasyNetwork/pull/375>`_)
- Clarify ``AsyncBackend.create_condition_var()`` behavior with lock argument. (`#377 <https://github.com/francis-clairicia/EasyNetwork/pull/377>`_)
- Updated Copyright years. (`#388 <https://github.com/francis-clairicia/EasyNetwork/pull/388>`_)


`1.0.0 <https://github.com/francis-clairicia/EasyNetwork/releases/tag/1.0.0>`_ (2024-09-07)
===========================================================================================

- Initial stable release.
