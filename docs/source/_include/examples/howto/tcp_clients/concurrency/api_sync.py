from __future__ import annotations

import contextlib
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeAlias

from easynetwork.clients import TCPNetworkClient
from easynetwork.exceptions import StreamProtocolParseError
from easynetwork.protocol import StreamProtocol
from easynetwork.serializers import JSONSerializer

RequestType: TypeAlias = dict[str, Any]
ResponseType: TypeAlias = dict[str, Any]


def consumer(response: ResponseType) -> None:
    # Do some stuff...

    print(response)


def receiver_worker(
    client: TCPNetworkClient[RequestType, ResponseType],
    executor: ThreadPoolExecutor,
) -> None:
    while True:
        try:
            # Pass timeout=None to get an infinite iterator.
            # It will be terminated when the client.close() method has been called.
            for response in client.iter_received_packets(timeout=None):
                executor.submit(consumer, response)
        except StreamProtocolParseError:
            print("Parsing error")
            traceback.print_exc()
            continue


def do_main_stuff(client: TCPNetworkClient[RequestType, ResponseType]) -> None:
    while True:
        # Do some stuff...
        request = {"data": 42}

        client.send_packet(request)


def main() -> None:
    remote_address = ("localhost", 9000)
    protocol = StreamProtocol(JSONSerializer())

    with contextlib.ExitStack() as exit_stack:
        # thread pool executor setup
        executor = exit_stack.enter_context(ThreadPoolExecutor())

        # connect to remote
        client = TCPNetworkClient(remote_address, protocol)

        # receiver_worker thread setup
        receiver_worker_thread = threading.Thread(
            target=receiver_worker,
            args=(client, executor),
        )
        receiver_worker_thread.start()
        exit_stack.callback(receiver_worker_thread.join)

        # add the client close, so it will be closed
        # before joining the thread
        exit_stack.enter_context(client)

        # Setup done, let's go
        do_main_stuff(client)


if __name__ == "__main__":
    main()
