Installation
============

To use EasyNetwork, first install it using pip:

.. code-block:: console

   (.venv) $ pip install easynetwork


Optional dependencies
---------------------

EasyNetwork has no required dependencies, but the library comes with a bunch of optional dependencies to meet specific needs.

Here is the full list:

* Serializer extensions:

   * ``cbor``: Installs the required dependencies for :class:`.CBORSerializer`.

   * ``encryption``: Installs the required dependencies for :class:`.EncryptorSerializer`.

   * ``msgpack``: Installs the required dependencies for :class:`.MessagePackSerializer`.

* Asynchronous I/O extensions:

   .. todo::

      Reference backend customization section

   * ``sniffio``: Installs the version supported and tested of `sniffio <https://github.com/python-trio/sniffio>`_.

   * ``uvloop``: Installs the version supported and tested of `uvloop <https://github.com/MagicStack/uvloop>`_.

      .. todo::

         Document uvloop known issues and caveats


Example where the ``cbor`` and ``msgpack`` extensions are installed:

.. code-block:: console

   (.venv) $ pip install "easynetwork[cbor,msgpack]"
