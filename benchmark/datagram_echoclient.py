#!/usr/bin/env python3
# Originally come from uvloop
# https://github.com/MagicStack/uvloop and https://github.com/MagicStack/vmbench


from __future__ import annotations

import argparse
import collections
import concurrent.futures
import json
import socket
import sys
import time
from typing import Literal, assert_never

from tool.client import RequestReport, TestReport, WorkerTestReport, dump_report, print_report


def run_test(
    socket_family: int,
    address: str | tuple[str, int],
    message_size: int,
    duration: float,
    socket_timeout: float,
) -> WorkerTestReport:
    sock = socket.socket(socket_family, socket.SOCK_DGRAM)

    REQSIZE = message_size

    msg = b"x" * message_size

    with sock:
        sock.settimeout(socket_timeout)
        if socket_family == socket.AF_INET:
            sock.bind(("127.0.0.1", 0))
        sock.connect(address)

        times_per_request: collections.deque[RequestReport] = collections.deque()
        recv_buf = bytearray(REQSIZE)

        test_start_time = test_end_time = time.perf_counter()
        while (test_end_time - test_start_time) < duration:
            request_start_time = time.perf_counter()
            sock.send(msg)
            nrecv = sock.recv_into(recv_buf)
            if nrecv < REQSIZE:
                raise SystemExit()
            test_end_time = request_end_time = time.perf_counter()
            times_per_request.append(RequestReport(start_time=request_start_time, end_time=request_end_time))

    return WorkerTestReport(start_time=test_start_time, end_time=test_end_time, times_per_request=list(times_per_request))


def main() -> None:
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--msize", default=1024, type=int, help="message size in bytes")
    parser.add_argument("--duration", default=30, type=int, help="duration of test in seconds")
    parser.add_argument("--timeout", default=2, type=int, help="socket timeout in seconds")
    parser.add_argument("--concurrency", dest="workers", default=3, type=int, help="number of workers")
    parser.add_argument("--addr", default="127.0.0.1:25000", type=str, help="address:port of echoserver")
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
    with concurrent.futures.ProcessPoolExecutor(max_workers=nb_workers) as e:
        workers_list = [
            e.submit(
                run_test,
                socket_family=SOCKFAMILY,
                address=SOCKADDR,
                message_size=message_size,
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
            print_report(report, show_transfer=False)
        case "json":
            json.dump(dump_report(report, show_transfer=False), sys.stdout)
        case _:
            assert_never(output_format)


if __name__ == "__main__":
    main()
