"""Fixed-destination, bounded TCP relay for loopback-published Docker ingress.

The relay alone joins a host-accessible bridge. Application services stay on internal
networks, without default internet routes. Listeners bind only the ingress bridge IP,
so a decoy cannot use an internal relay address to reach the analyst service.
"""

import select
import socket
import socketserver
import threading
import time
from typing import Any


class RelayServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address: tuple[str, int], target: tuple[str, int]) -> None:
        self.target = target
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(address, Relay)

    def process_request(self, request: Any, address: Any) -> None:
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request: Any, address: Any) -> None:
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

    def handle_error(self, request: Any, client_address: Any) -> None:
        pass


class Relay(socketserver.BaseRequestHandler):
    server: RelayServer
    request: socket.socket

    def handle(self) -> None:
        self.request.settimeout(3)
        try:
            with socket.create_connection(self.server.target, timeout=3) as upstream:
                pairs = {self.request: upstream, upstream: self.request}
                counts = {peer: 0 for peer in pairs}
                readers = list(pairs)
                started = time.monotonic()
                while readers and time.monotonic() - started < 1800:
                    ready, _, _ = select.select(readers, [], [], 60)
                    if not ready:
                        return
                    for source in ready:
                        data = source.recv(16384)
                        if not data:
                            readers.remove(source)
                            pairs[source].shutdown(socket.SHUT_WR)
                            continue
                        counts[source] += len(data)
                        if counts[source] > 32 * 1024 * 1024:
                            return
                        pairs[source].sendall(data)
        except OSError:
            pass


def main() -> None:
    # Alias exists only on the host-accessible network. Never listen on 0.0.0.0.
    host = socket.gethostbyname("local-ingress")
    servers = [
        RelayServer((host, port), (name, port))
        for port, name in ((8761, "portal"), (8762, "analyst"), (8763, "mqtt"))
    ]
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()
    try:
        for thread in threads:
            thread.join()
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
