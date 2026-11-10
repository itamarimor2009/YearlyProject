"""
protocol.py - The "language" that the client app and the filter server speak
on connection B (inside the TLS connection).

Every message is ONE line of JSON text that ends with a newline character "\n".
Examples:
    client -> server:  {"type": "check", "id": 7, "host": "www.ynet.com"}
    server -> client:  {"type": "result", "id": 7, "decision": "allow", "rule": null}

The full list of messages is in docs/ARCHITECTURE.md, section 6.
"""

import json

# The version of the protocol. The client sends it in the "hello" message.
PROTOCOL_VERSION = 1

# The longest message (in bytes) that we agree to read.
# This protects the server and the client from huge messages.
MAX_LINE_LENGTH = 4096

# --- Message types ---
HELLO = "hello"          # client -> server: "this is me, here is my token"
HELLO_OK = "hello_ok"    # server -> client: "login OK"
CHECK = "check"          # client -> server: "may I open this site?"
RESULT = "result"        # server -> client: "allow" or "block"
PING = "ping"            # client -> server: "are you there?" (the server answers it; our client
                         #   doesn't need it yet, because it reconnects by itself)
PONG = "pong"            # server -> client: "yes"
ERROR = "error"          # server -> client: something went wrong

# --- Decisions ---
ALLOW = "allow"
BLOCK = "block"

# --- Error codes ---
ERR_UNAUTHORIZED = "unauthorized"                # wrong first message, client_id or token
ERR_BAD_REQUEST = "bad_request"                  # not JSON, unknown type, invalid host name
ERR_TOO_LONG = "too_long"                        # a line longer than MAX_LINE_LENGTH
ERR_UNSUPPORTED_VERSION = "unsupported_version"  # "hello" with another protocol version
ERR_INTERNAL = "internal"                        # reserved for server failures (not used yet)


class ProtocolError(Exception):
    """
    Raised when the other side sends something that breaks the protocol rules
    (for example: a message that is too long, or that is not valid JSON).
    'code' is one of the ERR_... error codes above.
    """

    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code


def send_message(sock, message):
    """
    Send one message on the socket.
    'message' is a dictionary. It is turned into one line of JSON text.
    """
    line = json.dumps(message) + "\n"
    data = line.encode("utf-8")
    if len(data) > MAX_LINE_LENGTH:
        raise ProtocolError(ERR_TOO_LONG, "Message is too long to send")
    sock.sendall(data)


def receive_message(reader):
    """
    Read one message.

    'reader' is a file-like object made from the socket with sock.makefile("rb").
    It lets us read the socket line by line.

    Returns the message as a dictionary,
    or None if the other side closed the connection.
    """
    # Read at most MAX_LINE_LENGTH + 1 bytes, so we can notice a line that is too long.
    line = reader.readline(MAX_LINE_LENGTH + 1)

    if line == b"":
        return None  # The connection was closed.

    if len(line) > MAX_LINE_LENGTH or not line.endswith(b"\n"):
        raise ProtocolError(ERR_TOO_LONG, "Message is too long")

    try:
        message = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ProtocolError(ERR_BAD_REQUEST, "Message is not valid JSON")

    # Every message must be a JSON object (a dictionary) with a "type" field.
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise ProtocolError(ERR_BAD_REQUEST, "Message must be a JSON object with a 'type'")

    return message


def make_error(code, text, request_id=None):
    """Build an "error" message (a dictionary) ready to be sent."""
    return {"type": ERROR, "id": request_id, "code": code, "message": text}
