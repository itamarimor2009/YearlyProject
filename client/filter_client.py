"""
filter_client.py - Connection B: the secure connection from the client app to the filter server.

The FilterClient keeps ONE TLS connection open to the server.
check(host) sends a question and WAITS on the socket for the answer.

The browser opens many connections at the same time (many threads in LocalProxy),
but all of them share this one connection. A lock makes sure that only one
question at a time travels on the socket, so answers never get mixed up.
"""

import logging
import socket
import ssl
import threading
import time

from common import protocol
from common.protocol import ProtocolError
from common.tls_settings import describe_connection, use_diffie_hellman

logger = logging.getLogger("filter")

# The answer when the server can't be reached. The proxy then blocks the site ("fail closed").
UNAVAILABLE = "unavailable"

# After a failed connection, wait this many seconds before trying again.
# Without this, every browser request would wait for its own timeout while the server is down.
RETRY_WAIT_SECONDS = 5


class FilterClient:
    """Asks the filter server whether sites are allowed."""

    def __init__(self, config):
        """'config' is the settings dictionary from config/client.json."""
        self.server_host = config["server_host"]
        self.server_port = config["server_port"]
        self.client_id = config["client_id"]
        self.token = config["token"]
        self.timeout = config["check_timeout_seconds"]
        self.tls_context = self.create_tls_context(config["server_cert"], config.get("tls_keylog_file"))

        self.lock = threading.Lock()  # Only one question at a time on the socket.
        self.tls_socket = None        # None means "not connected".
        self.reader = None
        self.next_request_id = 1
        # When the last connection attempt failed (time.time() seconds).
        # 0 means "long ago", so the very first attempt is never delayed.
        self.last_failure_time = 0

    def create_tls_context(self, server_cert_file, keylog_file):
        """
        Prepare the TLS settings for the client side.
        - Only TLS 1.3, with X25519 Diffie-Hellman key exchange (see common/tls_settings.py).
        - We trust ONLY our own server's certificate (server.crt). This is called "pinning".
          Diffie-Hellman alone does not stop a man-in-the-middle; checking the certificate does.
        - check_hostname is on: the certificate must contain the server's IP / name.
        - keylog_file (optional, ONLY for the Wireshark demo): saves the session keys to a
          file so Wireshark can decrypt our own traffic. Never use it in real use.
        """
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # verifies certificates by default
        use_diffie_hellman(context)
        context.load_verify_locations(cafile=server_cert_file)
        if keylog_file:
            context.keylog_filename = keylog_file
            logger.warning("DEMO MODE: TLS keys are saved to %s (for Wireshark only)", keylog_file)
        return context

    def connect(self):
        """Open the TLS connection to the server and log in with "hello"."""
        raw_socket = socket.create_connection((self.server_host, self.server_port), timeout=self.timeout)
        try:
            # The TLS handshake (including the Diffie-Hellman key exchange) happens here.
            tls_socket = self.tls_context.wrap_socket(raw_socket, server_hostname=self.server_host)
        except (ssl.SSLError, OSError):
            raw_socket.close()
            raise

        self.tls_socket = tls_socket
        self.reader = tls_socket.makefile("rb")
        logger.info("Connected to filter server %s:%d (%s)",
                    self.server_host, self.server_port, describe_connection(tls_socket))

        # Log in.
        protocol.send_message(self.tls_socket, {
            "type": protocol.HELLO,
            "version": protocol.PROTOCOL_VERSION,
            "client_id": self.client_id,
            "token": self.token,
        })
        reply = protocol.receive_message(self.reader)
        if reply is None or reply["type"] != protocol.HELLO_OK:
            raise ProtocolError(protocol.ERR_UNAUTHORIZED,
                                "The server refused the login. Check client_id and token in config/client.json")
        logger.info("Logged in to the filter server as '%s'", self.client_id)

    def disconnect(self):
        """Close the connection (if it is open)."""
        if self.reader is not None:
            self.reader.close()
        if self.tls_socket is not None:
            self.tls_socket.close()
        self.reader = None
        self.tls_socket = None

    def try_connect(self):
        """Connect now (used when the client app starts). Returns True if it worked."""
        with self.lock:
            try:
                self.connect()
                return True
            except (OSError, ProtocolError) as error:
                logger.warning("Could not connect to the filter server: %s", error)
                self.disconnect()
                self.last_failure_time = time.time()
                return False

    def check(self, host):
        """
        Ask the server about one site.
        Returns protocol.ALLOW, protocol.BLOCK, or UNAVAILABLE (server can't be reached).

        Many browser threads call this at the same time; the lock makes them take turns,
        because they all share the one TLS connection.
        If there is no connection, it connects first (but not more often than once every
        RETRY_WAIT_SECONDS, so the browser isn't kept waiting while the server is down).
        """
        with self.lock:
            # Two tries: if the old connection was closed by the server (for example after
            # a long idle time), the first try fails and the second one reconnects.
            for attempt in range(2):
                if self.tls_socket is None:
                    # Don't keep trying while the server is down.
                    if time.time() - self.last_failure_time < RETRY_WAIT_SECONDS:
                        return UNAVAILABLE
                    try:
                        self.connect()
                    except (OSError, ProtocolError) as error:
                        logger.warning("Could not connect to the filter server: %s", error)
                        self.disconnect()
                        self.last_failure_time = time.time()
                        return UNAVAILABLE

                try:
                    return self.ask(host)
                except (OSError, ProtocolError) as error:
                    logger.warning("Lost connection to the filter server: %s", error)
                    self.disconnect()

            return UNAVAILABLE

    def ask(self, host):
        """
        Send one "check" message and wait for the "result". (The lock is already held.)
        Returns protocol.ALLOW or protocol.BLOCK. Network problems raise an exception,
        which check() handles.
        """
        request_id = self.next_request_id
        self.next_request_id = self.next_request_id + 1

        protocol.send_message(self.tls_socket, {"type": protocol.CHECK, "id": request_id, "host": host})
        reply = protocol.receive_message(self.reader)

        if reply is None:
            raise ConnectionError("The server closed the connection")

        if reply["type"] == protocol.RESULT and reply.get("id") == request_id:
            if reply.get("decision") == protocol.ALLOW:
                return protocol.ALLOW
            return protocol.BLOCK

        # An error (for example "not a valid host name") or a strange reply: block, to be safe.
        logger.warning("Unexpected reply from the server for %s: %s", host, reply)
        return protocol.BLOCK
