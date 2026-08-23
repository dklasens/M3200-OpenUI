#!/usr/bin/env python3
"""Pair a modem DIAG TCP stream with one local analysis client.

The modem-side listener is intended to be reached through an SSH reverse
forward.  The client listener defaults to loopback so the diagnostic stream is
never exposed to the LAN.
"""

import argparse
import selectors
import socket


def endpoint(value: str) -> tuple[str, int]:
    host, separator, port = value.rpartition(":")
    if not separator or not host:
        raise argparse.ArgumentTypeError("expected HOST:PORT")
    return host, int(port)


def listen(address: tuple[str, int]) -> socket.socket:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(address)
    server.listen(1)
    return server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modem", type=endpoint, default=("127.0.0.1", 43555))
    parser.add_argument("--client", type=endpoint, default=("127.0.0.1", 43556))
    args = parser.parse_args()

    modem_listener = listen(args.modem)
    client_listener = listen(args.client)
    print(f"waiting for modem on {args.modem[0]}:{args.modem[1]}", flush=True)
    modem, modem_peer = modem_listener.accept()
    print(f"modem connected from {modem_peer}", flush=True)
    print(f"waiting for client on {args.client[0]}:{args.client[1]}", flush=True)
    client, client_peer = client_listener.accept()
    print(f"client connected from {client_peer}", flush=True)
    modem_listener.close()
    client_listener.close()

    selector = selectors.DefaultSelector()
    selector.register(modem, selectors.EVENT_READ, client)
    selector.register(client, selectors.EVENT_READ, modem)
    transferred = 0
    try:
        while True:
            for key, _ in selector.select():
                try:
                    payload = key.fileobj.recv(1024 * 1024)
                except ConnectionResetError:
                    print(
                        f"stream reset after {transferred} bytes",
                        flush=True,
                    )
                    return
                if not payload:
                    print(f"stream closed after {transferred} bytes", flush=True)
                    return
                key.data.sendall(payload)
                transferred += len(payload)
    finally:
        modem.close()
        client.close()


if __name__ == "__main__":
    main()
