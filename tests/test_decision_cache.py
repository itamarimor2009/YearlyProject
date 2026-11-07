"""
test_decision_cache.py - Tests for client/decision_cache.py.

A fake clock is used: the time is passed in as a number, so no test ever sleeps.
"""

import threading
import unittest

from client.decision_cache import DecisionCache


class DecisionCacheTest(unittest.TestCase):
    """Tests for the DecisionCache class."""

    def test_missing_host_gives_none(self):
        """A host we never saved has no answer."""
        cache = DecisionCache()
        self.assertIsNone(cache.get("a.com", 300, now=0))

    def test_fresh_answer_is_returned(self):
        """An answer younger than max_age is returned."""
        cache = DecisionCache()
        cache.put("a.com", "allow", now=100)
        self.assertEqual(cache.get("a.com", 300, now=399), "allow")

    def test_old_answer_is_not_fresh(self):
        """An answer exactly as old as max_age is no longer fresh."""
        cache = DecisionCache()
        cache.put("a.com", "block", now=100)
        self.assertIsNone(cache.get("a.com", 300, now=400))

    def test_offline_uses_longer_age(self):
        """The same old answer is usable with the bigger offline limit."""
        cache = DecisionCache(keep_seconds=3600)
        cache.put("a.com", "block", now=0)
        self.assertIsNone(cache.get("a.com", 300, now=1000))
        self.assertEqual(cache.get("a.com", 3600, now=1000), "block")

    def test_too_old_entry_is_deleted(self):
        """An entry older than keep_seconds is removed."""
        cache = DecisionCache(keep_seconds=3600)
        cache.put("a.com", "allow", now=0)
        self.assertIsNone(cache.get("a.com", 99999, now=3600))
        self.assertEqual(cache.size(), 0)

    def test_full_cache_removes_oldest_saved(self):
        """When full, the entry saved longest ago is removed first."""
        cache = DecisionCache(max_entries=2)
        cache.put("a.com", "allow", now=1)
        cache.put("b.com", "allow", now=2)
        cache.put("c.com", "allow", now=3)
        self.assertEqual(cache.size(), 2)
        self.assertIsNone(cache.get("a.com", 300, now=4))
        self.assertEqual(cache.get("b.com", 300, now=4), "allow")

    def test_saving_again_counts_as_new(self):
        """Saving a host again protects it from being removed first."""
        cache = DecisionCache(max_entries=2)
        cache.put("a.com", "allow", now=1)
        cache.put("b.com", "allow", now=2)
        cache.put("a.com", "block", now=3)
        cache.put("c.com", "allow", now=4)
        self.assertEqual(cache.get("a.com", 300, now=5), "block")
        self.assertIsNone(cache.get("b.com", 300, now=5))

    def test_many_threads(self):
        """Many threads saving at once never break the cache."""
        cache = DecisionCache(max_entries=50)

        def work(number):
            for i in range(200):
                cache.put("h%d-%d.com" % (number, i), "allow", now=1)

        threads = [threading.Thread(target=work, args=(n,)) for n in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(cache.size(), 50)


if __name__ == "__main__":
    unittest.main()
