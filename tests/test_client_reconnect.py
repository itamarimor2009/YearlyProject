"""
test_client_reconnect.py - Tests for the increasing waits of FilterClient.

No real sleeping and no real network: a fake clock is used, and connect() is replaced
by a small function that fails or works on demand.
"""

import unittest

from client import filter_client
from client.filter_client import UNAVAILABLE, FilterClient

CONFIG = {
    "server_host": "127.0.0.1",
    "server_port": 1,
    "client_id": "test",
    "token": "x",
    "check_timeout_seconds": 1,
    "server_cert": None,
}


class FakeClock:
    """A clock that only moves when the test says so."""

    def __init__(self):
        """Start at time 1000."""
        self.now = 1000.0

    def __call__(self):
        """Return the current fake time."""
        return self.now


class ReconnectTests(unittest.TestCase):
    """The wait grows after failures and resets after a success."""

    def setUp(self):
        """Make a client without TLS settings, with a fake clock and a switchable connect()."""
        original = FilterClient.create_tls_context
        FilterClient.create_tls_context = lambda self, cert, keylog: None
        self.addCleanup(setattr, FilterClient, "create_tls_context", original)
        self.client = FilterClient(CONFIG)
        self.clock = FakeClock()
        self.client.clock = self.clock
        self.server_up = False
        self.connect_calls = 0
        self.client.connect = self.fake_connect
        self.client.ask = lambda host: "allow"

    def fake_connect(self):
        """Pretend to connect: fails while server_up is False."""
        self.connect_calls = self.connect_calls + 1
        if not self.server_up:
            raise ConnectionRefusedError("server is down")
        self.client.tls_socket = object()

    def fail_once(self):
        """Wait out the current waiting time, then make one failed attempt."""
        self.clock.now = self.clock.now + self.client.retry_wait + 0.1
        self.assertEqual(self.client.check("a.com"), UNAVAILABLE)

    def test_wait_grows_and_stops_at_maximum(self):
        """The waits are 1, 2, 4, 8, 16, 30, 30."""
        waits = []
        for i in range(7):
            self.fail_once()
            waits.append(self.client.retry_wait)
        self.assertEqual(waits, [1, 2, 4, 8, 16, 30, 30])

    def test_no_connection_attempt_while_waiting(self):
        """Inside the waiting time the network is not touched."""
        self.assertEqual(self.client.check("a.com"), UNAVAILABLE)
        calls = self.connect_calls
        self.clock.now = self.clock.now + 0.5
        self.assertEqual(self.client.check("a.com"), UNAVAILABLE)
        self.assertEqual(self.connect_calls, calls)

    def test_wait_resets_after_success(self):
        """After a good connection the next failure waits only 1 second again."""
        for i in range(5):
            self.fail_once()
        self.assertEqual(self.client.retry_wait, 16)
        self.server_up = True
        self.clock.now = self.clock.now + 17
        self.assertEqual(self.client.check("a.com"), "allow")
        self.assertEqual(self.client.retry_wait, filter_client.FIRST_RETRY_WAIT_SECONDS)
        self.assertIsNone(self.client.last_failure_time)

        self.server_up = False
        self.client.tls_socket = None
        self.assertEqual(self.client.check("a.com"), UNAVAILABLE)
        self.assertEqual(self.client.retry_wait, 1)


if __name__ == "__main__":
    unittest.main()
