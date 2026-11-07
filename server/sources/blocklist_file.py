"""
blocklist_file.py - Reads blocked sites from a text file (data/blacklist.txt).

File format:
    # this is a comment
    facebook.com
    tiktok.com

One domain per line. "#" starts a comment. Empty lines are ignored.
"""

import os

from common.domains import normalize_host
from server.sources.base import RuleSource


class BlocklistFileSource(RuleSource):
    """A source of blocked sites that is a text file on the server."""

    kind = "file"

    def __init__(self, path):
        """'path' is the location of the text file."""
        self.path = path
        self.name = "file:" + os.path.basename(path)

    def read_domains(self):
        """Read the file and return (domains, problems). See RuleSource.read_domains()."""
        domains = []
        problems = []

        with open(self.path, "r", encoding="utf-8") as blocklist_file:
            line_number = 0
            for line in blocklist_file:
                line_number = line_number + 1

                # Remove a comment ("#" and everything after it) and spaces.
                text = line.split("#")[0].strip()
                if text == "":
                    continue

                domain = normalize_host(text)
                if domain is None:
                    problems.append("line " + str(line_number) + ": not a valid domain: " + text)
                elif domain in domains:
                    problems.append("line " + str(line_number) + ": duplicate: " + domain)
                else:
                    domains.append(domain)

        return domains, problems
