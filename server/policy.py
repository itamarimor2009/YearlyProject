"""
policy.py - Decides if a site is allowed or blocked.

The PolicyEngine knows nothing about sockets or SQL.
It only asks the Repository "is this domain blocked?".
The flow chart of this decision is in docs/ARCHITECTURE.md, section 7.
"""

from common.domains import candidate_domains, normalize_host
from common.protocol import ALLOW, BLOCK


class Decision:
    """
    The answer for one site.

    host   - the cleaned site name, e.g. "www.facebook.com"
    action - ALLOW or BLOCK
    rule   - the blocked domain that matched (e.g. "facebook.com"), or None when allowed
    """

    def __init__(self, host, action, rule):
        self.host = host
        self.action = action
        self.rule = rule


class PolicyEngine:
    """Checks site names against the blocklist."""

    def __init__(self, repository):
        """'repository' is where the blocklist is stored (see server/storage)."""
        self.repository = repository

    def check(self, host):
        """
        Decide about one site.
        Returns a Decision, or None if 'host' is not a valid site name.
        """
        clean_host = normalize_host(host)
        if clean_host is None:
            return None

        # "www.facebook.com" -> check "www.facebook.com", then "facebook.com".
        for domain in candidate_domains(clean_host):
            if self.repository.is_blocked(domain):
                return Decision(clean_host, BLOCK, domain)

        # Not in the blocklist -> allowed (this is a blocklist, not an allowlist).
        return Decision(clean_host, ALLOW, None)
