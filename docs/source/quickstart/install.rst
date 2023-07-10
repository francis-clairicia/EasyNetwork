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

   .. todo::

      Add cross-reference links

   * ``cbor``: Installs the required dependencies for ``CBORSerializer``.

   * ``encryption``: Installs the required dependencies for ``EncryptorSerializer``.

   * ``msgpack``: Installs the required dependencies for ``MessagePackSerializer``.

* Asynchronous I/O extensions:

   .. todo::

      Reference backend customization section

   * ``sniffio``: Installs the version supported and tested of `sniffio <https://github.com/python-trio/sniffio>`_.

   * ``uvloop``: Installs the version supported and tested of `uvloop <https://github.com/MagicStack/uvloop>`_.


Example where the ``cbor`` and ``msgpack`` extensions are installed:

.. code-block:: console

   (.venv) $ pip install "easynetwork[cbor,msgpack]"
