#!/usr/bin/env python3
# Originally come from uvloop
# https://github.com/MagicStack/uvloop and https://github.com/MagicStack/vmbench


from __future__ import annotations

import argparse
import collections
import concurrent.futures
import gc
import json
import multiprocessing
import multiprocessing.synchronize
import socket
import ssl
import sys
from typing import Literal, assert_never

from tool.client import RequestReport, TestReport, WorkerTestReport, dump_report, print_report


def run_test(
    barrier: multiprocessing.synchronize.Barrier,
    socket_family: int,
    address: str | tuple[str, int],
    over_ssl: bool,
    message_size: int,
    messages_per_request: int,
    duration: float,
    socket_timeout: float,
) -> WorkerTestReport:
    if messages_per_request <= 0:
        raise ValueError(f"{messages_per_request=}")

    sock = socket.socket(socket_family, socket.SOCK_STREAM)

    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except (OSError, NameError):
        pass

    if over_ssl:
        client_context = ssl.create_default_context()
        client_context.check_hostname = False
        client_context.verify_mode = ssl.CERT_NONE
        sock = client_context.wrap_socket(sock)

    REQSIZE = message_size * messages_per_request

    msg = b"x" * (message_size - 1) + b"\n"
    msg *= messages_per_request

    with sock:
        gc.disable()
        gc.collect(2)

        sock.settimeout(socket_timeout)
        sock.connect(address)

        times_per_request: collections.deque[RequestReport] = collections.deque()
        recv_buf = bytearray(REQSIZE)

        from time import perf_counter

        barrier.wait(timeout=1)

        current_test_duration = 0.0
        while current_test_duration < duration:
            request_start_time = perf_counter()
            sock.sendall(msg)
            nrecv = 0
            while nrecv < REQSIZE:
                nbytes = sock.recv_into(recv_buf)
                if not nbytes:
                    raise SystemExit()
                nrecv += nbytes
            request_end_time = perf_counter()
            current_test_duration += request_end_time - request_start_time
            times_per_request.append(RequestReport(start_time=request_start_time, end_time=request_end_time))

    return WorkerTestReport(
        times_per_request=list(times_per_request),
        messages_per_request=messages_per_request,
    )


def main() -> None:
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--msize", default=1024, type=int, help="message size in bytes")
    parser.add_argument("--mpr", default=1, type=int, help="messages per request")
    parser.add_argument("--duration", default=30, type=int, help="duration of test in seconds")
    parser.add_argument("--timeout", default=2, type=int, help="socket timeout in seconds")
    parser.add_argument("--concurrency", dest="workers", default=3, type=int, help="number of workers")
    parser.add_argument("--addr", default="127.0.0.1:25000", type=str, help="address:port of echoserver")
    parser.add_argument("--ssl", default=False, action="store_true")
    parser.add_argument("--output-format", default="text", choices=["text", "json"], help="Report output format")
    args = parser.parse_args()

    SOCKFAMILY = socket.AF_INET
    if args.addr.startswith("file:"):
        SOCKFAMILY = socket.AF_UNIX
        SOCKADDR = args.addr[5:]
    else:
        SOCKADDR = args.addr.split(":")
        SOCKADDR[1] = int(SOCKADDR[1])
        SOCKADDR = tuple(SOCKADDR)

    nb_workers: int = args.workers
    message_size: int = args.msize
    mp_context = multiprocessing.get_context("spawn")
    with (
        mp_context.Manager() as manager,
        concurrent.futures.ProcessPoolExecutor(max_workers=nb_workers, mp_context=mp_context) as e,
    ):
        barrier: multiprocessing.synchronize.Barrier = manager.Barrier(nb_workers)  # type: ignore[attr-defined]
        workers_list = [
            e.submit(
                run_test,
                barrier=barrier,
                socket_family=SOCKFAMILY,
                address=SOCKADDR,
                over_ssl=args.ssl,
                message_size=message_size,
                messages_per_request=args.mpr,
                duration=args.duration,
                socket_timeout=args.timeout,
            )
            for _ in range(nb_workers)
        ]

        concurrent.futures.wait(workers_list)
        errors: list[BaseException] = [exc for worker in workers_list if (exc := worker.exception()) is not None]
        if errors:
            raise BaseExceptionGroup("Some workers have raised an exception", errors)

        report = TestReport(message_size, [worker.result() for worker in workers_list])

    output_format: Literal["text", "json"] = args.output_format

    match output_format:
        case "text":
            print_report(report)
        case "json":
            json.dump(dump_report(report), sys.stdout)
        case _:
            assert_never(output_format)


if __name__ == "__main__":
    main()
