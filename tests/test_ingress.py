import socket
import threading
import unittest

from miragetransit.ingress import RelayServer


class IngressTests(unittest.TestCase):
    def test_fixed_destination_and_half_close_preserve_response(self):
        upstream = socket.socket()
        upstream.bind(("127.0.0.1", 0))
        upstream.listen(1)
        payload = b"synthetic transport" * 3000

        def echo():
            with upstream:
                conn, _ = upstream.accept()
                with conn:
                    data = bytearray()
                    while chunk := conn.recv(16384):
                        data.extend(chunk)
                    conn.sendall(bytes(data)[::-1])

        thread = threading.Thread(target=echo)
        thread.start()
        relay = RelayServer(("127.0.0.1", 0), upstream.getsockname())
        server_thread = threading.Thread(target=relay.serve_forever)
        server_thread.start()
        try:
            with socket.create_connection(relay.server_address, timeout=3) as client:
                client.sendall(payload)
                client.shutdown(socket.SHUT_WR)
                received = bytearray()
                while chunk := client.recv(16384):
                    received.extend(chunk)
                self.assertEqual(bytes(received), payload[::-1])
        finally:
            relay.shutdown()
            relay.server_close()
            server_thread.join()
            thread.join()

    def test_unavailable_upstream_closes_instead_of_open_proxy(self):
        closed = socket.socket()
        closed.bind(("127.0.0.1", 0))
        address = closed.getsockname()
        closed.close()
        relay = RelayServer(("127.0.0.1", 0), address)
        thread = threading.Thread(target=relay.serve_forever)
        thread.start()
        try:
            with socket.create_connection(relay.server_address, timeout=3) as client:
                self.assertEqual(client.recv(1), b"")
        finally:
            relay.shutdown()
            relay.server_close()
            thread.join()
