************
Installation
************

To use EasyNetwork, first install it using :program:`pip`:

.. code-block:: console

   (.venv) $ pip install easynetwork


.. _optional-dependencies:

Optional Dependencies
=====================

EasyNetwork comes with several optional dependencies to meet specific needs.

Here is the full list:

* Serializer extensions:

   * ``cbor``: Installs the required dependencies for :class:`.CBORSerializer`.

   * ``msgpack``: Installs the required dependencies for :class:`.MessagePackSerializer`.

* Asynchronous I/O extensions:

   * ``trio``: Installs the *minimum* version supported of :github:repo:`trio <python-trio/trio>`.

.. warning::

   :mod:`trio` is an alpha project and we reserve the right to make semantic changes to the backend implementation
   and **update the minimum supported version at any time**.

   Also, to avoid having to make a new release for every 0.x release, the minor is *not* pinned. Keep in mind that this can lead
   to `breaking changes <https://github.com/python-trio/trio/issues/1>`_ after updating trio.

Example where the ``cbor`` and ``msgpack`` extensions are installed:

.. code-block:: console

   (.venv) $ pip install "easynetwork[cbor,msgpack]"
