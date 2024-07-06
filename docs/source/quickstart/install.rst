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


Example where the ``cbor`` and ``msgpack`` extensions are installed:

.. code-block:: console

   (.venv) $ pip install "easynetwork[cbor,msgpack]"
