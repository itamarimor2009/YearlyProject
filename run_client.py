"""
run_client.py - Starts the client app on the user's computer.

Usage (from the project folder):
    python run_client.py

Then set the browser's proxy (HTTP and HTTPS) to 127.0.0.1, port 8080.
Settings are read from config/client.json.
"""

import logging
import os

from client.filter_client import FilterClient
from client.local_proxy import LocalProxy
from common.config import load_config

CONFIG_FILE = os.path.join("config", "client.json")


def main():
    """Read the settings, connect to the filter server, and start the local proxy."""
    # Work from the project folder, so the paths in the config file always work.
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    config = load_config(CONFIG_FILE)
    filter_client = FilterClient(config)

    # Try to connect now, so we see right away if something is wrong.
    # If it fails, the client still starts: it will block sites and keep retrying.
    if not filter_client.try_connect():
        logging.warning("Starting anyway. Sites will be blocked until the filter server is reachable.")

    proxy = LocalProxy(config["local_port"], filter_client, config["allowed_ports"])
    try:
        proxy.start()
    except KeyboardInterrupt:
        print("\nClient stopped.")


if __name__ == "__main__":
    main()
