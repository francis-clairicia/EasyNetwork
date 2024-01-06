#!/usr/bin/env python3
# Copied from uvloop
# https://github.com/MagicStack/uvloop


from __future__ import annotations

import argparse
import concurrent.futures
import socket
import time

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--msize", default=1000, type=int, help="message size in bytes")
    parser.add_argument("--num", default=200000, type=int, help="number of messages")
    parser.add_argument("--times", default=1, type=int, help="number of times to run the test")
    parser.add_argument("--workers", default=3, type=int, help="number of workers")
    parser.add_argument("--addr", default="127.0.0.1:26000", type=str, help="address:port of echoserver")
    args = parser.parse_args()

    unix = False
    if args.addr.startswith("file:"):
        unix = True
        addr = args.addr[5:]
    else:
        addr = args.addr.split(":")
        addr[1] = int(addr[1])
        addr = tuple(addr)
    print(f"will connect to: {addr}")

    MSGSIZE = args.msize
    REQSIZE = MSGSIZE

    msg = b"x" * MSGSIZE

    def run_test(n: int) -> None:
        print("Sending", n, "messages")

        if unix:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        with sock:
            sock.bind(("127.0.0.1", 0))
            sock.connect(addr)

            recv_buf = bytearray(REQSIZE)

            while n > 0:
                sock.send(msg)
                nrecv = sock.recv_into(recv_buf)
                if nrecv < REQSIZE:
                    raise SystemExit()
                n -= 1

    TIMES = args.times
    N = args.workers
    NMESSAGES = args.num
    start = time.time()
    for i in range(TIMES):
        if TIMES > 1:
            print(f"test {i + 1}/{TIMES}")
        with concurrent.futures.ProcessPoolExecutor(max_workers=N) as e:
            for _ in range(N):
                e.submit(run_test, NMESSAGES)
    end = time.time()
    duration = end - start
    print(NMESSAGES * N * TIMES, "in", duration)
    print(NMESSAGES * N * TIMES / duration, "requests/sec")
