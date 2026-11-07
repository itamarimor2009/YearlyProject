"""
base.py - The Repository "interface": the list of things the server can ask the database.

The rest of the server only calls these methods. It does not know if the data
is kept in SQLite, in another database, or somewhere else.
To use a different database later, write a new class with the same methods
(see sqlite_repo.py for the SQLite version).
"""


class Repository:
    """
    Base class for all repositories.
    Every method here must be written again (overridden) in a real repository class.
    """

    def create_tables(self):
        """Create the tables if they don't exist yet."""
        raise NotImplementedError

    # --- Blocklist ---

    def replace_source_domains(self, source_name, source_kind, domains):
        """
        Delete all blocked sites that came from this source and insert 'domains' instead.
        Returns how many domains were saved.
        """
        raise NotImplementedError

    def is_blocked(self, domain):
        """Return True if exactly this domain is in the blocklist (and enabled)."""
        raise NotImplementedError

    def count_blocked_sites(self):
        """Return how many enabled blocked sites there are."""
        raise NotImplementedError

    # --- Clients ---

    def save_client(self, client_id, token_hash):
        """Add a client, or give an existing client a new token."""
        raise NotImplementedError

    def get_client(self, client_id):
        """
        Return (token_hash, enabled) for this client,
        or None if there is no such client.
        """
        raise NotImplementedError

    # --- Access log ---

    def add_log(self, client_id, client_ip, host, decision, rule):
        """Write one row to the access log."""
        raise NotImplementedError

    def get_recent_logs(self, count):
        """
        Return the latest 'count' log rows, newest first.
        Each row is (ts, client_id, client_ip, host, decision, rule).
        """
        raise NotImplementedError
