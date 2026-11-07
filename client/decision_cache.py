"""
decision_cache.py - Remembers the server's answers (allow / block) for a while.

Why: the browser opens many connections to the same sites. Asking the server for every
one is slow, and when the server is down we can still use an answer we saved earlier.

The key is the cleaned host name. For every host we store the decision and the time
it was saved. The time is always passed in by the caller (default: now), so the tests
can use a fake clock instead of sleeping.
"""

import threading
import time


class DecisionCache:
    """A small thread-safe dictionary: host -> (decision, time saved)."""

    def __init__(self, max_entries=1000, keep_seconds=3600):
        """
        max_entries  - the most hosts we remember. When full, the oldest saved one is removed.
        keep_seconds - entries older than this are useless (even offline) and get deleted.
        """
        self.max_entries = max_entries
        self.keep_seconds = keep_seconds
        self.entries = {}              # host -> (decision, saved_time)
        self.lock = threading.Lock()   # Many browser threads use the cache at the same time.

    def put(self, host, decision, now=None):
        """Save an answer. Saving a host again counts as new (it moves to the end)."""
        if now is None:
            now = time.time()
        with self.lock:
            # Delete first, so the re-added key goes to the END of the dictionary.
            # A dict remembers insertion order, so the FIRST key is always the oldest saved.
            if host in self.entries:
                del self.entries[host]
            self.entries[host] = (decision, now)

            while len(self.entries) > self.max_entries:
                oldest_host = next(iter(self.entries))
                del self.entries[oldest_host]

    def get(self, host, max_age_seconds, now=None):
        """
        Return the saved decision, or None if there is none that is young enough.
        'max_age_seconds' is how old the answer may be:
          - cache_seconds for a normal lookup (a "fresh" answer)
          - offline_grace_seconds when the server can't be reached
        """
        if now is None:
            now = time.time()
        with self.lock:
            if host not in self.entries:
                return None
            decision, saved_time = self.entries[host]
            age = now - saved_time

            # Too old even for offline use: delete it.
            if age >= self.keep_seconds:
                del self.entries[host]
                return None

            if age < max_age_seconds:
                return decision
            return None

    def size(self):
        """How many hosts are saved right now."""
        with self.lock:
            return len(self.entries)
