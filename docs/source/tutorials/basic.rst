Basic tutorial
==============

.. include:: ../_include/sync-async-variants.rst


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

.. Links

.. _FTP: https://fr.wikipedia.org/wiki/File_Transfer_Protocol
