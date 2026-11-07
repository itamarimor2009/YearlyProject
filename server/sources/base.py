"""
base.py - The RuleSource "interface": what every source of blocked sites must provide.

To add a new kind of source later, write a new class that inherits from RuleSource,
set 'name' and 'kind', and write read_domains().
"""


class RuleSource:
    """
    Base class for all sources of blocked sites.

    name - a unique name, saved in the "sources" table (e.g. "file:blacklist.txt")
    kind - what type of source this is (e.g. "file")
    """

    name = "unnamed"
    kind = "unknown"

    def read_domains(self):
        """
        Read the source and return two lists:
          domains  - the valid, cleaned domain names
          problems - text messages about lines that were skipped
        """
        raise NotImplementedError
