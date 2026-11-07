"""
sqlite_repo.py - The Repository written with SQLite (Python's built-in sqlite3 module).

Two simple rules keep this safe:
1. Every method opens its OWN connection and closes it at the end.
   The server runs many threads, and SQLite connections must not be shared
   between threads. Opening a connection to a local file is very fast.
2. All SQL uses "?" placeholders. We never glue user text into SQL,
   so SQL injection is impossible.
"""

import os
import sqlite3

from server.storage.base import Repository

# The file with the CREATE TABLE commands, in the same folder as this file.
SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "schema.sql")


class SqliteRepository(Repository):
    """Keeps the blocklist, the clients and the access log in one SQLite file."""

    def __init__(self, db_file):
        """'db_file' is the path of the database file, e.g. "data/filter.db"."""
        self.db_file = db_file

    def _connect(self):
        """Open a new connection to the database file."""
        # timeout=10: if another thread is writing, wait up to 10 seconds.
        return sqlite3.connect(self.db_file, timeout=10)

    def create_tables(self):
        """Create the tables (from schema.sql) if they don't exist yet."""
        folder = os.path.dirname(self.db_file)
        if folder != "":
            os.makedirs(folder, exist_ok=True)

        with open(SCHEMA_FILE, "r", encoding="utf-8") as schema_file:
            schema = schema_file.read()

        connection = self._connect()
        try:
            # WAL mode lets the server read while an import is writing.
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(schema)
            connection.commit()
        finally:
            connection.close()

    # --- Blocklist ---

    def replace_source_domains(self, source_name, source_kind, domains):
        """Replace all domains of one source with the new list (in one transaction)."""
        connection = self._connect()
        try:
            # Find the source, or create it if this is the first import.
            row = connection.execute(
                "SELECT id FROM sources WHERE name = ?", (source_name,)
            ).fetchone()
            if row is None:
                cursor = connection.execute(
                    "INSERT INTO sources (name, kind) VALUES (?, ?)",
                    (source_name, source_kind),
                )
                source_id = cursor.lastrowid
            else:
                source_id = row[0]

            # Remove the old list of this source and insert the new one.
            connection.execute("DELETE FROM blocked_sites WHERE source_id = ?", (source_id,))
            for domain in domains:
                connection.execute(
                    "INSERT OR IGNORE INTO blocked_sites (domain, source_id) VALUES (?, ?)",
                    (domain, source_id),
                )

            connection.execute(
                "UPDATE sources SET last_imported = CURRENT_TIMESTAMP WHERE id = ?",
                (source_id,),
            )

            # Save everything together. If something failed above, nothing is saved.
            connection.commit()
            return len(domains)
        finally:
            connection.close()

    def is_blocked(self, domain):
        """Return True if this exact domain is an enabled blocked site."""
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT 1 FROM blocked_sites WHERE domain = ? AND enabled = 1 LIMIT 1",
                (domain,),
            ).fetchone()
            return row is not None
        finally:
            connection.close()

    def count_blocked_sites(self):
        """Return how many enabled blocked sites there are."""
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT COUNT(*) FROM blocked_sites WHERE enabled = 1"
            ).fetchone()
            return row[0]
        finally:
            connection.close()

    # --- Clients ---

    def save_client(self, client_id, token_hash):
        """Add a new client, or replace the token of an existing one."""
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT id FROM clients WHERE client_id = ?", (client_id,)
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO clients (client_id, token_hash) VALUES (?, ?)",
                    (client_id, token_hash),
                )
            else:
                connection.execute(
                    "UPDATE clients SET token_hash = ?, enabled = 1 WHERE client_id = ?",
                    (token_hash, client_id),
                )
            connection.commit()
        finally:
            connection.close()

    def get_client(self, client_id):
        """Return (token_hash, enabled) for this client, or None if it doesn't exist."""
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT token_hash, enabled FROM clients WHERE client_id = ?",
                (client_id,),
            ).fetchone()
            if row is None:
                return None
            return (row[0], row[1] == 1)
        finally:
            connection.close()

    # --- Access log ---

    def add_log(self, client_id, client_ip, host, decision, rule):
        """Write one row to the access log."""
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO access_log (client_id, client_ip, host, decision, rule) "
                "VALUES (?, ?, ?, ?, ?)",
                (client_id, client_ip, host, decision, rule),
            )
            connection.commit()
        finally:
            connection.close()

    def get_recent_logs(self, count):
        """Return the latest 'count' log rows, newest first."""
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT ts, client_id, client_ip, host, decision, rule "
                "FROM access_log ORDER BY id DESC LIMIT ?",
                (count,),
            ).fetchall()
            return rows
        finally:
            connection.close()
