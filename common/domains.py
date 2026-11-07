"""
domains.py - Helper functions for site names (host names).

Two jobs:
1. normalize_host()     - clean a host name so that "WWW.Ynet.com." and "www.ynet.com"
                          are treated as the same site, and reject invalid names.
2. candidate_domains()  - list the host and all its "parent" domains, so that
                          blocking "ynet.com" also blocks "www.ynet.com".
"""

import ipaddress
import re

# A full host name may be at most 253 characters long.
MAX_HOST_LENGTH = 253

# One part of a host name (between dots), for example "www" or "ynet".
# Allowed: letters, digits and "-" (but not at the start or the end), 1-63 characters.
LABEL_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def is_ip_address(host):
    """Return True if 'host' is an IP address like "142.250.1.1" or "::1"."""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def normalize_host(host):
    """
    Clean a host name and check that it is valid.

    Steps:
      - remove spaces, change to lowercase
      - remove [ ] around IPv6 addresses
      - remove a dot at the end ("ynet.com." -> "ynet.com")
      - convert non-English names to the "xn--" form (called IDNA)

    Returns the clean host name, or None if the name is not valid.
    """
    if not isinstance(host, str):
        return None

    host = host.strip().lower()

    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]

    if host.endswith("."):
        host = host[:-1]

    if host == "":
        return None

    # IP addresses are fine as they are.
    if is_ip_address(host):
        return host

    # Convert names like "דוגמה.com" to "xn--...com".
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None

    if len(host) > MAX_HOST_LENGTH:
        return None

    # Check every part between the dots.
    for label in host.split("."):
        if not LABEL_PATTERN.match(label):
            return None

    return host


def candidate_domains(host):
    """
    Return the host and all its parent domains, from the most specific to the least.

    Example:
        "a.b.ynet.com"  ->  ["a.b.ynet.com", "b.ynet.com", "ynet.com"]

    We stop before the last part ("com"), because nobody blocks a whole ending.
    An IP address is returned as it is.

    'host' must already be cleaned with normalize_host().
    """
    if is_ip_address(host):
        return [host]

    parts = host.split(".")
    if len(parts) == 1:
        return [host]  # A name with no dots, like "localhost".

    candidates = []
    for start in range(len(parts) - 1):
        candidates.append(".".join(parts[start:]))
    return candidates
