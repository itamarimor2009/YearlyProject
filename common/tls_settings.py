"""
tls_settings.py - TLS settings shared by the client and the server.

The key exchange of TLS 1.3 is Diffie-Hellman. We ask for the X25519 version
(Elliptic-Curve Diffie-Hellman), so it is clear what the connection uses.
Without this, new OpenSSL versions pick a "hybrid" method that mixes X25519
with a post-quantum method (ML-KEM).
"""

import ssl


def use_diffie_hellman(context):
    """Set up 'context' for TLS 1.3 with X25519 Diffie-Hellman key exchange."""
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    # set_groups() exists in new Python versions (3.15+). Older versions already use X25519.
    if hasattr(context, "set_groups"):
        context.set_groups("X25519")


def describe_connection(tls_socket):
    """Return text like "TLSv1.3, key exchange X25519, cipher TLS_AES_256_GCM_SHA384"."""
    text = tls_socket.version()
    if hasattr(tls_socket, "group"):
        text = text + ", key exchange " + str(tls_socket.group())
    text = text + ", cipher " + tls_socket.cipher()[0]
    return text
