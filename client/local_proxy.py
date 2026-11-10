"""
local_proxy.py - Connection A: the proxy that the browser talks to.

The browser's proxy setting points to 127.0.0.1:8080, so the browser sends
every request here. For each new browser connection we:
  1. read the request and find the site name and port,
  2. ask the filter server (through FilterClient) whether the site is allowed,
  3. if allowed: connect to the website and pass the bytes in both directions,
     if blocked: answer the browser with "403 Forbidden".

The browser sends two kinds of requests:
  HTTPS:  CONNECT www.ynet.com:443 HTTP/1.1          (then encrypted bytes follow)
  HTTP:   GET http://www.ynet.com/news HTTP/1.1      (a normal, unencrypted request)
"""

import html
import logging
import os
import socket
import threading
from urllib.parse import urlsplit

from client.filter_client import UNAVAILABLE
from client.relay import relay
from common import protocol

logger = logging.getLogger("proxy")

# The longest request head (first line + headers) we accept from the browser.
MAX_HEAD_SIZE = 16384

# Seconds to wait for the browser or the website before giving up.
SOCKET_TIMEOUT_SECONDS = 30

BLOCK_PAGE_FILE = os.path.join(os.path.dirname(__file__), "block_page.html")


class LocalProxy:
    """Receives browser requests, asks the filter, and opens or blocks the site."""

    def __init__(self, port, filter_client, allowed_ports):
        """
        'port'          - the local port the browser connects to (e.g. 8080)
        'filter_client' - a FilterClient, used to ask the server
        'allowed_ports' - website ports we agree to open (e.g. [80, 443])
        """
        self.port = port
        self.filter_client = filter_client
        self.allowed_ports = allowed_ports
        with open(BLOCK_PAGE_FILE, "r", encoding="utf-8") as page_file:
            self.block_page = page_file.read()

    def start(self):
        """Listen for the browser forever. Each browser connection gets its own thread."""
        listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # 127.0.0.1 = only programs on THIS computer can use the proxy.
        listen_socket.bind(("127.0.0.1", self.port))
        listen_socket.listen(100)
        logger.info("Local proxy ready. Set the browser's proxy to 127.0.0.1:%d", self.port)

        try:
            while True:
                browser_socket, _ = listen_socket.accept()
                thread = threading.Thread(target=self.handle_browser, args=(browser_socket,), daemon=True)
                thread.start()
        finally:
            listen_socket.close()

    def handle_browser(self, browser_socket):
        """Handle one browser connection and always close it at the end."""
        try:
            self.process_request(browser_socket)
        except OSError as error:
            logger.debug("Browser connection ended: %s", error)
        finally:
            browser_socket.close()

    def process_request(self, browser_socket):
        """The main steps for one browser connection (see the top of this file)."""
        browser_socket.settimeout(SOCKET_TIMEOUT_SECONDS)

        # Step 1: read the request and find the host and port.
        head, extra_data = read_request_head(browser_socket)
        if head is None:
            return

        # The first line looks like "CONNECT www.ynet.com:443 HTTP/1.1":
        # method, target, and HTTP version, separated by spaces.
        first_line = head.split("\r\n")[0]
        parts = first_line.split(" ")
        if len(parts) != 3:
            self.send_page(browser_socket, "400 Bad Request", "Bad request", "", "The request could not be read.")
            return
        method = parts[0].upper()
        target = parts[1]

        if method == "CONNECT":
            host, port = parse_connect_target(target)
            path = None
        else:
            host, port, path = parse_http_url(target)

        if host is None:
            self.send_page(browser_socket, "400 Bad Request", "Bad request", target, "The address could not be read.")
            return

        if port not in self.allowed_ports:
            logger.info("Refused %s:%d (port not allowed)", host, port)
            self.send_page(browser_socket, "403 Forbidden", "Port not allowed", host,
                           "Only ports " + str(self.allowed_ports) + " are allowed.")
            return

        # Step 2: ask the filter server. This WAITS for the answer (usually a few milliseconds).
        decision = self.filter_client.check(host)

        if decision == protocol.BLOCK:
            logger.info("BLOCKED %s", host)
            self.send_page(browser_socket, "403 Forbidden", "Site blocked", host,
                           "This site is blocked by the site filter.")
            return

        if decision == UNAVAILABLE:
            logger.info("BLOCKED %s (filter server unavailable)", host)
            self.send_page(browser_socket, "503 Service Unavailable", "Filter server unavailable", host,
                           "The site filter server can't be reached, so sites are blocked. Try again soon.")
            return

        # Step 3: allowed -> connect to the website (connection C).
        try:
            website_socket = socket.create_connection((host, port), timeout=SOCKET_TIMEOUT_SECONDS)
        except OSError as error:
            logger.info("Could not reach %s:%d: %s", host, port, error)
            self.send_page(browser_socket, "502 Bad Gateway", "Site not reachable", host,
                           "The site could not be reached.")
            return

        try:
            if method == "CONNECT":
                # HTTPS: tell the browser the tunnel is ready. From now on the browser
                # and the website talk TLS to each other through us.
                browser_socket.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                # Bytes that arrived together with the CONNECT line belong to the website.
                if extra_data != b"":
                    website_socket.sendall(extra_data)
            else:
                # HTTP: send the request to the website, in the form a website expects.
                website_socket.sendall(rewrite_http_head(head, method, path) + extra_data)

            relay(browser_socket, website_socket)
        finally:
            website_socket.close()

    def send_page(self, browser_socket, status, title, host, message):
        """Send the browser a small HTML page with an HTTP status like "403 Forbidden"."""
        page = self.block_page.replace("{{TITLE}}", html.escape(title))
        page = page.replace("{{HOST}}", html.escape(host))
        page = page.replace("{{MESSAGE}}", html.escape(message))
        body = page.encode("utf-8")

        header = ("HTTP/1.1 " + status + "\r\n"
                  "Content-Type: text/html; charset=utf-8\r\n"
                  "Content-Length: " + str(len(body)) + "\r\n"
                  "Connection: close\r\n"
                  "\r\n")
        browser_socket.sendall(header.encode("ascii") + body)


def read_request_head(browser_socket):
    """
    Read from the browser until the end of the request head (an empty line "\r\n\r\n").

    Returns (head, extra_data):
      head       - the first line and headers, as text (or None if something went wrong)
      extra_data - bytes that arrived after the head (for example the start of a POST body)
    """
    data = b""
    while b"\r\n\r\n" not in data:
        if len(data) > MAX_HEAD_SIZE:
            return None, b""
        chunk = browser_socket.recv(4096)
        if chunk == b"":
            return None, b""  # The browser closed the connection.
        data = data + chunk

    end = data.index(b"\r\n\r\n") + 4
    # HTTP headers are plain bytes; "iso-8859-1" turns every byte into one character safely.
    head = data[:end].decode("iso-8859-1")
    return head, data[end:]


def parse_connect_target(target):
    """
    Split "www.ynet.com:443" into ("www.ynet.com", 443).
    Returns (None, None) if it can't be read.
    """
    if ":" not in target:
        return None, None

    host, port_text = target.rsplit(":", 1)
    host = host.strip("[]")  # IPv6 addresses come as [::1]:443
    if host == "" or not port_text.isdigit():
        return None, None
    return host, int(port_text)


def parse_http_url(url):
    """
    Split "http://www.ynet.com:8080/news?id=5" into
    ("www.ynet.com", 8080, "/news?id=5").
    The port is 80 when the address doesn't say one.
    Returns (None, None, None) if it can't be read.
    """
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None, None, None

    if parts.scheme != "http" or not parts.hostname:
        return None, None, None

    if port is None:
        port = 80

    path = parts.path
    if path == "":
        path = "/"
    if parts.query != "":
        path = path + "?" + parts.query

    return parts.hostname, port, path


def rewrite_http_head(head, method, path):
    """
    Change a proxy-style HTTP request into a normal one for the website.

    Browser to proxy:   GET http://www.ynet.com/news HTTP/1.1
    Proxy to website:   GET /news HTTP/1.1

    We also add "Connection: close", so the browser makes a NEW connection for
    the next request. That way every request is checked by the filter.
    """
    lines = head.split("\r\n")
    version = lines[0].split(" ")[2]
    new_lines = [method + " " + path + " " + version]

    for line in lines[1:]:
        if line == "":
            continue
        name = line.split(":")[0].strip().lower()
        # Remove headers about keeping the connection open; we set our own.
        if name in ("connection", "proxy-connection", "keep-alive"):
            continue
        new_lines.append(line)

    new_lines.append("Connection: close")
    return ("\r\n".join(new_lines) + "\r\n\r\n").encode("iso-8859-1")
