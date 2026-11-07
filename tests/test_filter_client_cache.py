"""
test_filter_client_cache.py - Tests FilterClient.check() with the cache, without a network.

ask_server() is replaced by a fake that counts questions and can pretend the server is down.
"""

import time
import unittest

from client.decision_cache import DecisionCache
from client.filter_client import UNAVAILABLE, FilterClient
from common.protocol import ALLOW, BLOCK


class FakeServerClient(FilterClient):
    """A FilterClient that never opens a socket."""

    def __init__(self, cache_seconds=300):
        """Only the cache part of FilterClient is set up."""
        self.cache_seconds = cache_seconds
        self.offline_grace_seconds = 3600
        self.cache = DecisionCache(1000, 3600)
        self.questions = 0
        self.answer = (ALLOW, True)

    def ask_server(self, host):
        """Count the question and return the prepared answer."""
        self.questions = self.questions + 1
        return self.answer


class FilterClientCacheTest(unittest.TestCase):
    """Tests for the cache and offline rules in check()."""

    def test_second_check_uses_cache(self):
        """The server is asked only once for the same host (any spelling)."""
        client = FakeServerClient()
        self.assertEqual(client.check("www.ynet.com"), ALLOW)
        self.assertEqual(client.check("WWW.Ynet.com."), ALLOW)
        self.assertEqual(client.questions, 1)

    def test_cache_off(self):
        """cache_seconds = 0: every check asks the server."""
        client = FakeServerClient(cache_seconds=0)
        client.check("a.com")
        client.check("a.com")
        self.assertEqual(client.questions, 2)

    def test_errors_are_not_cached(self):
        """An error reply (from_server False) is not saved."""
        client = FakeServerClient()
        client.answer = (BLOCK, False)
        client.check("a.com")
        client.check("a.com")
        self.assertEqual(client.questions, 2)

    def test_offline_uses_expired_answer(self):
        """Server down + old (not fresh, but within the grace time) answer: use it."""
        client = FakeServerClient()
        client.answer = (UNAVAILABLE, False)
        # Saved 1000 seconds ago: older than cache_seconds (300), younger than the grace (3600).
        client.cache.put("b.com", ALLOW, now=time.time() - 1000)
        self.assertEqual(client.check("b.com"), ALLOW)

    def test_offline_without_answer_is_unavailable(self):
        """Server down and nothing cached: fail closed."""
        client = FakeServerClient()
        client.answer = (UNAVAILABLE, False)
        self.assertEqual(client.check("a.com"), UNAVAILABLE)

    def test_offline_answer_too_old(self):
        """An answer older than offline_grace_seconds is not used."""
        client = FakeServerClient()
        client.answer = (UNAVAILABLE, False)
        client.cache.put("a.com", ALLOW, now=1)  # 1970: far too old
        self.assertEqual(client.check("a.com"), UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
