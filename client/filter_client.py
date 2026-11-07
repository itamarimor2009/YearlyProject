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

from client.decision_cache import DecisionCache
from common import protocol
from common.domains import normalize_host
from common.protocol import ProtocolError
from common.tls_settings import describe_connection, use_diffie_hellman

logger = logging.getLogger("filter")

# The answer when the server can't be reached. The proxy then blocks the site ("fail closed").
UNAVAILABLE = "unavailable"

# After a failed connection we wait before trying again, and the wait grows with every
# failure in a row: 1, 2, 4, 8, 16, 30, 30 ... seconds. It never gets longer than the maximum.
# Without any wait, every browser request would wait for its own timeout while the server is down.
FIRST_RETRY_WAIT_SECONDS = 1
MAX_RETRY_WAIT_SECONDS = 30

# Defaults for the optional cache settings (old config files without them still work).
DEFAULT_CACHE_SECONDS = 300           # an answer this young is used without asking the server
DEFAULT_OFFLINE_GRACE_SECONDS = 3600  # when the server is down, answers up to this old are used
DEFAULT_CACHE_MAX_ENTRIES = 1000


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

        # Cache settings. cache_seconds = 0 turns the cache (and the offline fallback) off.
        self.cache_seconds = config.get("cache_seconds", DEFAULT_CACHE_SECONDS)
        self.offline_grace_seconds = config.get("offline_grace_seconds", DEFAULT_OFFLINE_GRACE_SECONDS)
        self.cache = DecisionCache(config.get("cache_max_entries", DEFAULT_CACHE_MAX_ENTRIES),
                                   self.offline_grace_seconds)

        self.lock = threading.Lock()  # Only one question at a time on the socket.
        self.tls_socket = None        # None means "not connected".
        self.reader = None
        self.next_request_id = 1
        self.clock = time.time        # The clock. Tests replace it with a fake one, so they never sleep.
        self.retry_wait = FIRST_RETRY_WAIT_SECONDS  # How long we wait after the latest failure.
        self.last_failure_time = None  # When the last connection attempt failed (None = no failure yet).

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

    def connection_failed(self):
        """
        Remember that a connection attempt failed. Call this with the lock held.
        The waiting time is counted from now. The first failure waits 1 second; every further
        failure in a row doubles the wait (up to the maximum).
        """
        if self.last_failure_time is not None:
            self.retry_wait = self.retry_wait * 2
            if self.retry_wait > MAX_RETRY_WAIT_SECONDS:
                self.retry_wait = MAX_RETRY_WAIT_SECONDS
        self.last_failure_time = self.clock()

    def connection_succeeded(self):
        """Forget all earlier failures, so the next failure starts again at the shortest wait."""
        self.retry_wait = FIRST_RETRY_WAIT_SECONDS
        self.last_failure_time = None

    def must_wait(self):
        """True while we are still inside the waiting time after the last failed connection."""
        if self.last_failure_time is None:
            return False
        return self.clock() - self.last_failure_time < self.retry_wait

    def try_connect(self):
        """Connect now (used when the client app starts). Returns True if it worked."""
        with self.lock:
            try:
                self.connect()
                self.connection_succeeded()
                return True
            except (OSError, ProtocolError) as error:
                logger.warning("Could not connect to the filter server: %s", error)
                self.disconnect()
                self.connection_failed()
                return False

    def check(self, host):
        """
        Decide about one site. Returns protocol.ALLOW, protocol.BLOCK, or UNAVAILABLE.
        Order: 1) fresh cached answer  2) ask the server  3) offline: older cached answer
        4) UNAVAILABLE (the proxy then blocks: "fail closed").
        """
        # The cache is keyed by the cleaned host name. A bad name is never cached:
        # it goes to the server like in Phase 1 (the server answers "error" -> block).
        clean_host = normalize_host(host)
        use_cache = clean_host is not None and self.cache_seconds > 0

        if use_cache:
            cached = self.cache.get(clean_host, self.cache_seconds)
            if cached is not None:
                logger.info("%s %s (cache hit)", clean_host, cached)
                return cached

        decision, from_server = self.ask_server(host)

        if from_server:
            # Only real answers from the server are saved (never errors or "unavailable").
            if use_cache:
                self.cache.put(clean_host, decision)
            return decision

        if decision == UNAVAILABLE and use_cache:
            old = self.cache.get(clean_host, self.offline_grace_seconds)
            if old is not None:
                logger.warning("%s %s (offline: using cached answer)", clean_host, old)
                return old
            logger.warning("%s unavailable (offline: no cached answer, blocking)", clean_host)
        return decision

    def ask_server(self, host):
        """
        Ask the server about one site (holding the socket lock).
        Returns (decision, from_server). from_server is True only for a real "result"
        answer, so check() knows what may be saved in the cache.
        """
        with self.lock:
            # Two tries: if the old connection was closed by the server (for example after
            # a long idle time), the first try fails and the second one reconnects.
            for attempt in range(2):
                if self.tls_socket is None:
                    # Don't keep trying while the server is down.
                    if self.must_wait():
                        return UNAVAILABLE, False
                    try:
                        self.connect()
                        self.connection_succeeded()
                    except (OSError, ProtocolError) as error:
                        logger.warning("Could not connect to the filter server: %s", error)
                        self.disconnect()
                        self.connection_failed()
                        return UNAVAILABLE, False

                try:
                    return self.ask(host)
                except (OSError, ProtocolError) as error:
                    logger.warning("Lost connection to the filter server: %s", error)
                    self.disconnect()

            return UNAVAILABLE, False

    def ask(self, host):
        """
        Send one "check" message and wait for the "result". (The lock is already held.)
        Returns (decision, from_server): from_server is False for error replies.
        """
        request_id = self.next_request_id
        self.next_request_id = self.next_request_id + 1

        protocol.send_message(self.tls_socket, {"type": protocol.CHECK, "id": request_id, "host": host})
        reply = protocol.receive_message(self.reader)

        if reply is None:
            raise ConnectionError("The server closed the connection")

        if reply["type"] == protocol.RESULT and reply.get("id") == request_id:
            if reply.get("decision") == protocol.ALLOW:
                return protocol.ALLOW, True
            return protocol.BLOCK, True

        # An error (for example "not a valid host name") or a strange reply: block, to be safe.
        logger.warning("Unexpected reply from the server for %s: %s", host, reply)
        return protocol.BLOCK, False
