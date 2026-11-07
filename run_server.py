"""
run_server.py - Starts and manages the filter server.

Usage (from the project folder):
    python run_server.py run                      Start the server
    python run_server.py import                   Load data/blacklist.txt into the database
    python run_server.py add-client <client_id>   Register a client app and print its secret token
    python run_server.py logs [count]             Show the latest checks (default: 20)

All commands read their settings from config/server.json.
"""

import logging
import os
import secrets
import sys

from common.config import load_config
from server.importer import import_source
from server.sources.blocklist_file import BlocklistFileSource
from server.storage.sqlite_repo import SqliteRepository
from server.tls_server import FilterServer, hash_token

CONFIG_FILE = os.path.join("config", "server.json")

USAGE = """Usage:
    python run_server.py run
    python run_server.py import
    python run_server.py add-client <client_id>
    python run_server.py logs [count]"""


def setup_logging(log_file):
    """Print log messages on the screen and also save them in a file."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_file, encoding="utf-8")],
    )


def command_run(config, repository):
    """Import the blocklist file and start the server."""
    import_source(repository, BlocklistFileSource(config["blacklist_file"]))
    server = FilterServer(config, repository)
    server.start()


def command_import(config, repository):
    """Load the blocklist file into the database (the running server sees it right away)."""
    count = import_source(repository, BlocklistFileSource(config["blacklist_file"]))
    print("Done. The blocklist now has", count, "sites from", config["blacklist_file"])


def command_add_client(repository, client_id):
    """Create a client with a new random token, and print the token once."""
    token = secrets.token_urlsafe(24)  # 24 random bytes -> 32 characters of text
    repository.save_client(client_id, hash_token(token))
    print("Client '" + client_id + "' is registered.")
    print("Put these lines in the client's config/client.json:")
    print('    "client_id": "' + client_id + '",')
    print('    "token": "' + token + '",')
    print("The token is shown only now. If you lose it, run this command again to get a new one.")


def command_logs(repository, count):
    """Print the latest checks as a simple table."""
    rows = repository.get_recent_logs(count)
    if len(rows) == 0:
        print("No checks yet.")
        return

    print("%-19s  %-10s  %-15s  %-6s  %-30s  %s" % ("TIME (UTC)", "CLIENT", "IP", "RESULT", "HOST", "RULE"))
    for row in rows:
        ts, client_id, client_ip, host, decision, rule = row
        if rule is None:
            rule = ""
        print("%-19s  %-10s  %-15s  %-6s  %-30s  %s" % (ts, client_id, client_ip, decision, host, rule))


def main():
    """Read the command from the command line and run it."""
    # Work from the project folder, so the paths in the config file always work.
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    if len(sys.argv) < 2:
        print(USAGE)
        return

    command = sys.argv[1]
    config = load_config(CONFIG_FILE)
    repository = SqliteRepository(config["db_file"])
    repository.create_tables()
    setup_logging(config["log_file"])

    if command == "run":
        try:
            command_run(config, repository)
        except KeyboardInterrupt:
            print("\nServer stopped.")
    elif command == "import":
        command_import(config, repository)
    elif command == "add-client" and len(sys.argv) == 3:
        command_add_client(repository, sys.argv[2])
    elif command == "logs":
        count = 20
        if len(sys.argv) == 3:
            count = int(sys.argv[2])
        command_logs(repository, count)
    else:
        print(USAGE)


if __name__ == "__main__":
    main()
