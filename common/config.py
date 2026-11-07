"""
config.py - Reads a settings file (JSON) into a Python dictionary.

Both the client and the server keep their settings (ports, file names, ...)
in a JSON file inside the "config" folder.
"""

import json


def load_config(path):
    """Read the JSON file at 'path' and return its contents as a dictionary."""
    with open(path, "r", encoding="utf-8") as config_file:
        return json.load(config_file)
