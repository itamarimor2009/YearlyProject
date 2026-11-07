"""
test_end_to_end.py - Tests the whole system working together, on one computer:

    "browser" (this test) -> LocalProxy -> FilterClient ==TLS==> FilterServer -> SQLite
                                 |
                                 +--> a small test website (also started by this test)

Nothing here needs the internet. A temporary certificate is created with openssl,
so this test is skipped if openssl is not installed.
"""

import http.server
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest

from client.filter_client import UNAVAILABLE, FilterClient
from client.local_proxy import LocalProxy
from common.protocol import ALLOW, BLOCK
from server.importer import import_source
from server.sources.blocklist_file import BlocklistFileSource
from server.storage.sqlite_repo import SqliteRepository
from server.tls_server import FilterServer, hash_token

TOKEN = "test-token-123"


def free_port():
    """Ask the operating system for a TCP port that nobody is using."""
    temp_socket = socket.socket()
    temp_socket.bind(("127.0.0.1", 0))
    port = temp_socket.getsockname()[1]
    temp_socket.close()
    return port


def start_in_thread(function):
    """Run 'function' in a background thread (it may run forever)."""
    thread = threading.Thread(target=function, daemon=True)
    thread.start()


def wait_for_port(port):
    """Wait (up to 5 seconds) until something listens on this port."""
    for attempt in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return
        except OSError:
            time.sleep(0.1)


class QuietHandler(http.server.BaseHTTPRequestHandler):
    """The test website: answers every GET with "hello from the test site"."""

    def do_GET(self):
        body = b"hello from the test site"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # Don't print every request during the tests.


@unittest.skipIf(shutil.which("openssl") is None, "openssl is not installed")
class TestEndToEnd(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Runs once: create a certificate, a database, and start the server, website and proxy."""
        cls.folder = tempfile.mkdtemp()
        cert_file = os.path.join(cls.folder, "server.crt")
        key_file = os.path.join(cls.folder, "server.key")
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
             "-keyout", key_file, "-out", cert_file, "-subj", "/CN=127.0.0.1",
             "-addext", "subjectAltName=IP:127.0.0.1"],
            check=True, capture_output=True)

        # Database with a blocklist and one registered client.
        blocklist_file = os.path.join(cls.folder, "blacklist.txt")
        with open(blocklist_file, "w") as f:
            f.write("facebook.com\n")
        cls.repository = SqliteRepository(os.path.join(cls.folder, "filter.db"))
        cls.repository.create_tables()
        import_source(cls.repository, BlocklistFileSource(blocklist_file))
        cls.repository.save_client("pc-test", hash_token(TOKEN))

        # The filter server.
        server_port = free_port()
        server = FilterServer({"listen_host": "127.0.0.1", "listen_port": server_port,
                               "cert_file": cert_file, "key_file": key_file}, cls.repository)
        start_in_thread(server.start)
        wait_for_port(server_port)

        # The test website.
        cls.website_port = free_port()
        website = http.server.HTTPServer(("127.0.0.1", cls.website_port), QuietHandler)
        start_in_thread(website.serve_forever)

        # Settings for clients (the tests change client_id / token to test bad logins).
        cls.client_config = {"server_host": "127.0.0.1", "server_port": server_port,
                             "server_cert": cert_file, "client_id": "pc-test",
                             "token": TOKEN, "check_timeout_seconds": 3}

        # The local proxy, allowed to open the test website's port.
        cls.proxy_port = free_port()
        proxy = LocalProxy(cls.proxy_port, FilterClient(cls.client_config), [cls.website_port, 80, 443])
        start_in_thread(proxy.start)
        wait_for_port(cls.proxy_port)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder)

    def browser_get(self, url):
        """Send a GET request through the proxy, like a browser would. Returns the full answer."""
        browser = socket.create_connection(("127.0.0.1", self.proxy_port), timeout=10)
        browser.sendall(("GET " + url + " HTTP/1.1\r\nHost: x\r\n\r\n").encode("ascii"))
        answer = b""
        while True:
            data = browser.recv(4096)
            if data == b"":
                break
            answer = answer + data
        browser.close()
        return answer.decode("utf-8", "replace")

    # --- FilterClient talking to the real server over TLS ---

    def test_client_gets_allow_and_block(self):
        client = FilterClient(self.client_config)
        self.assertEqual(client.check("www.ynet.co.il"), ALLOW)
        self.assertEqual(client.check("www.facebook.com"), BLOCK)
        client.disconnect()

    def test_wrong_token_is_refused(self):
        config = dict(self.client_config)
        config["token"] = "wrong"
        client = FilterClient(config)
        self.assertEqual(client.check("www.ynet.co.il"), UNAVAILABLE)

    def test_server_logs_every_check(self):
        client = FilterClient(self.client_config)
        client.check("logged.example.com")
        client.disconnect()
        hosts = [row[3] for row in self.repository.get_recent_logs(20)]
        self.assertIn("logged.example.com", hosts)

    # --- The whole path: browser -> proxy -> filter -> website ---

    def test_allowed_site_through_proxy(self):
        answer = self.browser_get("http://127.0.0.1:" + str(self.website_port) + "/")
        self.assertIn("200", answer.split("\r\n")[0])
        self.assertIn("hello from the test site", answer)

    def test_blocked_site_through_proxy(self):
        answer = self.browser_get("http://www.facebook.com/")
        self.assertIn("403", answer.split("\r\n")[0])
        self.assertIn("Site blocked", answer)

    def test_port_not_allowed(self):
        answer = self.browser_get("http://127.0.0.1:1/")
        self.assertIn("403", answer.split("\r\n")[0])
        self.assertIn("Port not allowed", answer)


if __name__ == "__main__":
    unittest.main()
