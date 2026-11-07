"""
test_proxy_parsing.py - Tests for the helper functions in client/local_proxy.py
that read the browser's requests.
"""

import unittest

from client.local_proxy import parse_connect_target, parse_http_url, rewrite_http_head


class TestParsing(unittest.TestCase):

    def test_connect_target(self):
        self.assertEqual(parse_connect_target("www.ynet.com:443"), ("www.ynet.com", 443))
        self.assertEqual(parse_connect_target("[::1]:443"), ("::1", 443))
        self.assertEqual(parse_connect_target("no-port"), (None, None))
        self.assertEqual(parse_connect_target("host:abc"), (None, None))

    def test_http_url(self):
        self.assertEqual(parse_http_url("http://www.ynet.com/news?id=5"), ("www.ynet.com", 80, "/news?id=5"))
        self.assertEqual(parse_http_url("http://example.com:8080"), ("example.com", 8080, "/"))
        self.assertEqual(parse_http_url("ftp://example.com/"), (None, None, None))
        self.assertEqual(parse_http_url("/just/a/path"), (None, None, None))

    def test_rewrite_http_head(self):
        head = ("GET http://example.com/a HTTP/1.1\r\n"
                "Host: example.com\r\n"
                "Proxy-Connection: keep-alive\r\n"
                "Connection: keep-alive\r\n"
                "\r\n")
        result = rewrite_http_head(head, "GET", "/a").decode("iso-8859-1")
        self.assertEqual(result, "GET /a HTTP/1.1\r\nHost: example.com\r\nConnection: close\r\n\r\n")


if __name__ == "__main__":
    unittest.main()
