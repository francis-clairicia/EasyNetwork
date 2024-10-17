********
Overview
********

EasyNetwork completely encapsulates the socket handling, providing you with a higher level interface
that allows an application/software to completely handle the logic part with Python objects,
without worrying about how to process, send or receive data over the network.

The communication protocol can be whatever you want, be it JSON, Pickle, ASCII, structure, base64 encoded,
compressed, or any other format that is not part of the standard library.
You choose the data format and the library takes care of the rest.

This project is especially useful for simple **message** exchange between clients and servers.

Works with TCP, UDP, and Unix sockets.
