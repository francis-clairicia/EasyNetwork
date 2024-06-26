************
Installation
************

To use EasyNetwork, first install it using :program:`pip`:

.. code-block:: console

   (.venv) $ pip install easynetwork


.. _optional-dependencies:

Optional Dependencies
=====================

EasyNetwork has no required dependencies, but comes with many optional dependencies to meet specific needs.

Here is the full list:

* Serializer extensions:

   * ``cbor``: Installs the required dependencies for :class:`.CBORSerializer`.

   * ``msgpack``: Installs the required dependencies for :class:`.MessagePackSerializer`.

* Asynchronous I/O extensions:

   * ``sniffio``: Installs the version supported and tested of :github:repo:`sniffio <python-trio/sniffio>`, used by :func:`.ensure_backend`.


Example where the ``cbor`` and ``msgpack`` extensions are installed:

.. code-block:: console

   (.venv) $ pip install "easynetwork[cbor,msgpack]"
