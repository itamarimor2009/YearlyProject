"""
test_policy.py - Tests for the blocklist file, the importer, the SQLite repository
and the PolicyEngine, working together on a temporary database.
"""

import os
import shutil
import tempfile
import unittest

from common.protocol import ALLOW, BLOCK
from server.importer import import_source
from server.policy import PolicyEngine
from server.sources.blocklist_file import BlocklistFileSource
from server.storage.sqlite_repo import SqliteRepository


class TestPolicy(unittest.TestCase):

    def setUp(self):
        """Create a temporary folder with a small blocklist file and an empty database."""
        self.folder = tempfile.mkdtemp()
        self.blocklist_path = os.path.join(self.folder, "blacklist.txt")
        self.write_blocklist("# test list\nfacebook.com\nm.tiktok.com  # only mobile\n\nnot a domain\n")

        self.repository = SqliteRepository(os.path.join(self.folder, "test.db"))
        self.repository.create_tables()
        import_source(self.repository, BlocklistFileSource(self.blocklist_path))
        self.policy = PolicyEngine(self.repository)

    def tearDown(self):
        """Delete the temporary folder."""
        shutil.rmtree(self.folder)

    def write_blocklist(self, text):
        with open(self.blocklist_path, "w", encoding="utf-8") as blocklist_file:
            blocklist_file.write(text)

    def test_blocked_domain_and_subdomains(self):
        for host in ["facebook.com", "www.facebook.com", "a.b.facebook.com", "WWW.FACEBOOK.COM."]:
            decision = self.policy.check(host)
            self.assertEqual(decision.action, BLOCK, host)
            self.assertEqual(decision.rule, "facebook.com")

    def test_parent_is_not_blocked_by_subdomain_rule(self):
        self.assertEqual(self.policy.check("m.tiktok.com").action, BLOCK)
        self.assertEqual(self.policy.check("www.tiktok.com").action, ALLOW)

    def test_other_sites_are_allowed(self):
        decision = self.policy.check("www.ynet.com")
        self.assertEqual(decision.action, ALLOW)
        self.assertIsNone(decision.rule)

    def test_similar_name_is_not_blocked(self):
        # "notfacebook.com" is NOT a subdomain of "facebook.com".
        self.assertEqual(self.policy.check("notfacebook.com").action, ALLOW)

    def test_invalid_host(self):
        self.assertIsNone(self.policy.check("bad host"))

    def test_bad_lines_are_skipped(self):
        self.assertEqual(self.repository.count_blocked_sites(), 2)

    def test_reimport_replaces_the_list(self):
        self.write_blocklist("instagram.com\n")
        import_source(self.repository, BlocklistFileSource(self.blocklist_path))
        self.assertEqual(self.policy.check("facebook.com").action, ALLOW)
        self.assertEqual(self.policy.check("instagram.com").action, BLOCK)

    def test_access_log(self):
        self.repository.add_log("pc-1", "10.0.0.5", "www.facebook.com", BLOCK, "facebook.com")
        rows = self.repository.get_recent_logs(10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1:], ("pc-1", "10.0.0.5", "www.facebook.com", BLOCK, "facebook.com"))


if __name__ == "__main__":
    unittest.main()
