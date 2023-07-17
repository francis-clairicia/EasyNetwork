Practical application — Build a FTP server from scratch
=======================================================

.. include:: ../_include/sync-async-variants.rst


Goal
----

Yes, I know, you will never need to create your own FTP server (unless you want your own service). However, it is still interesting
to see the structure of such a model, based on a standardized communication protocol.

The `File Transfer Protocol`_ (as defined in :rfc:`959`) is a good example of how to set up a server with precise rules.

We are not going to implement all the queries (that's not the point). The tutorial will show you how to set up the infrastructure
and exploit all (or most) of the EasyNetwork library's features.


.. Links

.. _File Transfer Protocol: https://en.wikipedia.org/wiki/File_Transfer_Protocol
