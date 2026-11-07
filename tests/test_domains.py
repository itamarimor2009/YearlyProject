"""
test_domains.py - Tests for common/domains.py (cleaning host names and parent domains).
"""

import unittest

from common.domains import candidate_domains, normalize_host


class TestNormalizeHost(unittest.TestCase):
    """normalize_host() should clean good names and reject bad ones."""

    def test_lowercase_and_trailing_dot(self):
        self.assertEqual(normalize_host("WWW.Ynet.COM."), "www.ynet.com")

    def test_spaces_are_removed(self):
        self.assertEqual(normalize_host("  ynet.com  "), "ynet.com")

    def test_ip_addresses(self):
        self.assertEqual(normalize_host("142.250.1.1"), "142.250.1.1")
        self.assertEqual(normalize_host("[::1]"), "::1")

    def test_non_english_name_becomes_xn(self):
        self.assertTrue(normalize_host("דוגמה.com").startswith("xn--"))

    def test_bad_names(self):
        self.assertIsNone(normalize_host(""))
        self.assertIsNone(normalize_host("bad host.com"))
        self.assertIsNone(normalize_host("-start.com"))
        self.assertIsNone(normalize_host("a..b.com"))
        self.assertIsNone(normalize_host("x" * 300 + ".com"))
        self.assertIsNone(normalize_host(None))
        self.assertIsNone(normalize_host(12345))


class TestCandidateDomains(unittest.TestCase):
    """candidate_domains() should list the host and its parent domains."""

    def test_subdomains(self):
        self.assertEqual(candidate_domains("a.b.ynet.com"), ["a.b.ynet.com", "b.ynet.com", "ynet.com"])

    def test_two_parts(self):
        self.assertEqual(candidate_domains("ynet.com"), ["ynet.com"])

    def test_single_name(self):
        self.assertEqual(candidate_domains("localhost"), ["localhost"])

    def test_ip_address(self):
        self.assertEqual(candidate_domains("10.0.0.1"), ["10.0.0.1"])


if __name__ == "__main__":
    unittest.main()
