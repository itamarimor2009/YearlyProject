"""
importer.py - Loads blocked sites from a source (like blacklist.txt) into the database.
"""

import logging

logger = logging.getLogger("importer")


def import_source(repository, source):
    """
    Read all domains from 'source' and save them in the database.
    The new list REPLACES everything that came from this source before,
    so removing a line from the file also removes the block.

    Returns how many domains were saved.
    """
    domains, problems = source.read_domains()

    for problem in problems:
        logger.warning("%s: skipped %s", source.name, problem)

    count = repository.replace_source_domains(source.name, source.kind, domains)
    logger.info("Imported %d blocked sites from %s", count, source.name)
    return count
