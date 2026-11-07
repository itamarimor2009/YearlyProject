"""
test_protocol.py - Tests for common/protocol.py (sending and receiving JSON-line messages).

socket.socketpair() gives us two sockets that are already connected to each other,
so we can test sending and receiving without a real network.
"""

import socket
import unittest

from common import protocol
from common.protocol import ProtocolError


class TestProtocol(unittest.TestCase):

    def setUp(self):
        """Runs before every test: create two connected sockets."""
        self.left, self.right = socket.socketpair()
        self.reader = self.right.makefile("rb")

    def tearDown(self):
        """Runs after every test: close everything."""
        self.reader.close()
        self.left.close()
        self.right.close()

    def test_send_and_receive(self):
        message = {"type": "check", "id": 1, "host": "ynet.com"}
        protocol.send_message(self.left, message)
        self.assertEqual(protocol.receive_message(self.reader), message)

    def test_closed_connection_returns_none(self):
        self.left.close()
        self.assertIsNone(protocol.receive_message(self.reader))

    def test_too_long_line(self):
        self.left.sendall(b"x" * (protocol.MAX_LINE_LENGTH + 10) + b"\n")
        with self.assertRaises(ProtocolError) as result:
            protocol.receive_message(self.reader)
        self.assertEqual(result.exception.code, protocol.ERR_TOO_LONG)

    def test_not_json(self):
        self.left.sendall(b"hello there\n")
        with self.assertRaises(ProtocolError) as result:
            protocol.receive_message(self.reader)
        self.assertEqual(result.exception.code, protocol.ERR_BAD_REQUEST)

    def test_json_without_type(self):
        self.left.sendall(b'{"host": "ynet.com"}\n')
        with self.assertRaises(ProtocolError):
            protocol.receive_message(self.reader)


if __name__ == "__main__":
    unittest.main()
