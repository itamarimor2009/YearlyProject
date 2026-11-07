"""
access_logger.py - Records every check (allowed and blocked).

Each check becomes one row in the "access_log" table, and one line on the screen.
The future admin dashboard will be built on top of this table.
"""

import logging

logger = logging.getLogger("access")


class AccessLogger:
    """Writes check results to the database and to the server's log."""

    def __init__(self, repository):
        self.repository = repository

    def log_check(self, client_id, client_ip, decision):
        """Save one check. 'decision' is a Decision object from policy.py."""
        self.repository.add_log(client_id, client_ip, decision.host, decision.action, decision.rule)

        if decision.rule is None:
            logger.info("%s (%s) %s -> %s", client_id, client_ip, decision.host, decision.action)
        else:
            logger.info("%s (%s) %s -> %s (rule: %s)",
                        client_id, client_ip, decision.host, decision.action, decision.rule)
