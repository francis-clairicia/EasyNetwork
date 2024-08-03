.. note::

   This page uses two different API variants:

   * Synchronous API with classic ``def`` functions, usable in any context.

   * Asynchronous API with ``async def`` functions, using an :term:`asynchronous framework` to perform I/O operations.

   All asynchronous API examples assume that you are using either :mod:`asyncio` or :mod:`trio`,
   but you can use a different library thanks to the :doc:`asynchronous backend engine API </api/lowlevel/async/backend>`.
