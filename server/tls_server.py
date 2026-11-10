"""
tls_server.py - The network part of the filter server.

What it does:
1. Listens for client apps on a TCP port (9443 by default).
2. For every client, starts a new thread.
3. Turns the connection into a secure TLS connection. The key is agreed with
   Diffie-Hellman (built into TLS 1.3), and the server proves who it is with its certificate.
4. Checks the client's login ("hello" message with a token).
5. Answers "check" messages with "allow" or "block".

The drawings of these steps are in docs/ARCHITECTURE.md, section 5.
"""

import hashlib
import hmac
import logging
import socket
import ssl
import threading

from common import protocol
from common.protocol import ProtocolError
from common.tls_settings import describe_connection, use_diffie_hellman
from server.access_logger import AccessLogger
from server.policy import PolicyEngine

logger = logging.getLogger("server")

# A new client must finish the TLS handshake and log in within this many seconds.
# (Otherwise a slow or bad client could hold a thread for a long time.)
LOGIN_TIMEOUT_SECONDS = 10

# Close a logged-in client connection after this many seconds without any message.
IDLE_TIMEOUT_SECONDS = 600

# The most client connections the server handles at the same time.
MAX_CLIENTS = 100


def hash_token(token):
    """Return the SHA-256 hash of a token, as hex text. We store only hashes, never tokens."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class FilterServer:
    """The TLS server that answers allow/block questions from client apps."""

    def __init__(self, config, repository):
        """
        'config'     - the settings dictionary (from config/server.json)
        'repository' - the database (see server/storage)
        """
        self.listen_host = config["listen_host"]
        self.listen_port = config["listen_port"]
        self.repository = repository
        self.policy = PolicyEngine(repository)
        self.access_logger = AccessLogger(repository)
        self.tls_context = self.create_tls_context(config["cert_file"], config["key_file"])
        # A counter of free "places" for clients. Each connection takes one place
        # and gives it back when it ends.
        self.free_places = threading.BoundedSemaphore(MAX_CLIENTS)

    def create_tls_context(self, cert_file, key_file):
        """
        Prepare the TLS settings for the server side.
        - Only TLS 1.3 is allowed. TLS 1.3 always uses (Elliptic-Curve) Diffie-Hellman
          to agree on the encryption key.
        - The certificate and private key prove to clients that this is the real server.
        """
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        use_diffie_hellman(context)
        context.load_cert_chain(certfile=cert_file, keyfile=key_file)
        return context

    def start(self):
        """Listen for clients forever. Each client gets its own thread."""
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Allow restarting the server right away on the same port.
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((self.listen_host, self.listen_port))
        server_socket.listen(50)
        logger.info("Filter server listening on %s:%d", self.listen_host, self.listen_port)

        try:
            while True:
                client_socket, address = server_socket.accept()

                # Too many clients at once? Refuse this one instead of starting a thread.
                if not self.free_places.acquire(blocking=False):
                    logger.warning("Too many clients, refused connection from %s", address[0])
                    client_socket.close()
                    continue

                # daemon=True: the thread stops when the main program stops.
                thread = threading.Thread(target=self.handle_client,
                                          args=(client_socket, address), daemon=True)
                thread.start()
        finally:
            server_socket.close()

    def handle_client(self, client_socket, address):
        """Runs in its own thread for each client. Gives back the client's place at the end."""
        try:
            self.talk_to_client(client_socket, address)
        finally:
            self.free_places.release()

    def talk_to_client(self, client_socket, address):
        """Talk with one client app, from the TLS handshake until it disconnects."""
        client_ip = address[0]
        client_socket.settimeout(LOGIN_TIMEOUT_SECONDS)

        # Step 1: TLS handshake. Here the two sides do the Diffie-Hellman key exchange.
        try:
            tls_socket = self.tls_context.wrap_socket(client_socket, server_side=True)
        except (ssl.SSLError, OSError) as error:
            logger.warning("TLS handshake with %s failed: %s", client_ip, error)
            client_socket.close()
            return

        logger.info("TLS connection from %s (%s)", client_ip, describe_connection(tls_socket))

        # makefile() lets us read the socket line by line.
        reader = tls_socket.makefile("rb")
        try:
            # Step 2: login.
            client_id = self.do_hello(tls_socket, reader, client_ip)
            if client_id is not None:
                # Step 3: answer questions until the client leaves.
                # A logged-in client may stay quiet for longer.
                tls_socket.settimeout(IDLE_TIMEOUT_SECONDS)
                self.serve_requests(tls_socket, reader, client_id, client_ip)
        except ProtocolError as error:
            # The client broke the protocol rules: tell it why and disconnect.
            logger.warning("Protocol error from %s: %s", client_ip, error)
            self.try_send(tls_socket, protocol.make_error(error.code, str(error)))
        except OSError as error:
            # Network problem or timeout (socket.timeout is a kind of OSError).
            logger.info("Connection with %s ended: %s", client_ip, error)
        finally:
            reader.close()
            tls_socket.close()

    def do_hello(self, tls_socket, reader, client_ip):
        """
        The first message must be "hello" with a valid client_id and token.
        Returns the client_id if the login is OK, or None if the client was refused.
        """
        message = protocol.receive_message(reader)
        if message is None:
            return None

        if message["type"] != protocol.HELLO:
            self.refuse(tls_socket, client_ip, "first message must be hello")
            return None

        # A client that speaks another version of the protocol can't be served.
        if message.get("version") != protocol.PROTOCOL_VERSION:
            protocol.send_message(tls_socket, protocol.make_error(
                protocol.ERR_UNSUPPORTED_VERSION, "Server speaks protocol version 1"))
            return None

        client_id = message.get("client_id")
        token = message.get("token")
        if not isinstance(client_id, str) or not isinstance(token, str):
            self.refuse(tls_socket, client_ip, "missing client_id or token")
            return None

        if not self.is_valid_client(client_id, token):
            # repr() shows the name in quotes and turns special characters (like a new line)
            # into visible codes, so a client can't write fake lines into our log.
            self.refuse(tls_socket, client_ip, "wrong token or unknown client " + repr(client_id[:50]))
            return None

        protocol.send_message(tls_socket, {"type": protocol.HELLO_OK})
        logger.info("Client '%s' logged in from %s", client_id, client_ip)
        return client_id

    def is_valid_client(self, client_id, token):
        """Return True if this client exists, is enabled, and the token is correct."""
        client = self.repository.get_client(client_id)
        if client is None:
            return False

        stored_hash, enabled = client
        if not enabled:
            return False

        # compare_digest takes the same time whether the hashes match or not,
        # so an attacker can't guess the token by measuring the time.
        return hmac.compare_digest(hash_token(token), stored_hash)

    def refuse(self, tls_socket, client_ip, reason):
        """Log a failed login and tell the client it is not allowed."""
        logger.warning("Refused login from %s: %s", client_ip, reason)
        protocol.send_message(tls_socket, protocol.make_error(protocol.ERR_UNAUTHORIZED, "Login refused"))

    def serve_requests(self, tls_socket, reader, client_id, client_ip):
        """Read messages from a logged-in client and answer each one."""
        while True:
            message = protocol.receive_message(reader)
            if message is None:
                logger.info("Client '%s' disconnected", client_id)
                return

            request_id = message.get("id")

            if message["type"] == protocol.CHECK:
                self.handle_check(tls_socket, message, request_id, client_id, client_ip)
            elif message["type"] == protocol.PING:
                protocol.send_message(tls_socket, {"type": protocol.PONG, "id": request_id})
            else:
                protocol.send_message(tls_socket, protocol.make_error(
                    protocol.ERR_BAD_REQUEST, "Unknown message type", request_id))

    def handle_check(self, tls_socket, message, request_id, client_id, client_ip):
        """Answer one "check" message: decide, write the log, send the result."""
        decision = self.policy.check(message.get("host"))

        if decision is None:
            protocol.send_message(tls_socket, protocol.make_error(
                protocol.ERR_BAD_REQUEST, "Not a valid host name", request_id))
            return

        self.access_logger.log_check(client_id, client_ip, decision)

        protocol.send_message(tls_socket, {
            "type": protocol.RESULT,
            "id": request_id,
            "decision": decision.action,
            "rule": decision.rule,
        })

    def try_send(self, tls_socket, message):
        """Send a message, but ignore errors (used when we are closing anyway)."""
        try:
            protocol.send_message(tls_socket, message)
        except (OSError, ProtocolError):
            pass
