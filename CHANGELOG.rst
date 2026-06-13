=========
Changelog
=========

All notable changes to this project will be documented in this file.

The format is based on `Keep a Changelog <https://keepachangelog.com/en/1.0.0/>`_,
and this project adheres to `Semantic Versioning <https://semver.org/spec/v2.0.0.html>`_.

See also the `Release Notes <https://github.com/francis-clairicia/EasyNetwork/releases>`_.

To see unreleased changes, please see the `CHANGELOG on the main branch documentation <https://easynetwork.readthedocs.io/en/latest/changelog.html>`_.

.. towncrier release notes start

1.1.0 (2025-01-19)
==================

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

  * Low-level API :

     * In ``easynetwork.lowlevel.socket`` module:

        * Added ``UNIXSocketAttribute`` typed attributes set.

        * Added ``UnixCredentials``.

        * Added ``UnixSocketAddress``.

     * In ``easynetwork.lowlevel.api_async.backend`` module:

        * Added ``AsyncBackend.create_unix_stream_connection()``.

        * Added ``AsyncBackend.create_unix_datagram_endpoint()``.

        * Added ``AsyncBackend.create_unix_stream_listener()``.

        * Added ``AsyncBackend.create_unix_datagram_listener()``.

  PR: (`#389 <https://github.com/francis-clairicia/EasyNetwork/pull/389>`_)


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


1.0.0 (2024-09-07)
==================

- Initial stable release.
