# Working on this project

This is a **high-school** yearly project (not university). The student must understand and
present every line, so keep it simple.

## Rules

- **Simple Python only.** Standard library only. Plain classes, functions and loops.
  No ABCs/metaclasses, decorators you write yourself, async, dataclasses, type-hint-heavy code,
  clever comprehensions or one-liners.
- **Clear comments everywhere.** Every file starts with a docstring saying what it is for;
  every class and function has a docstring; comment the "why" of anything non-obvious.
- **Docs first.** `docs/ARCHITECTURE.md` is the source of truth and `docs/PLAN.md` holds the
  decisions and phases. Change the design in the docs first, then the code. Keep the Mermaid
  diagrams valid.
- **Tests.** Every change keeps `python -m unittest discover tests` green and adds tests for new
  behavior.
- **Keep the layering:** sockets → protocol → policy → repository → database. The server's
  network code never writes SQL; the PolicyEngine knows nothing about sockets.
- **Security basics stay:** TLS 1.3 + X25519, certificate pinning, tokens stored as hashes,
  `?` placeholders in SQL, size limits and timeouts on everything from the network.
- Never commit `config/server.json`, `config/client.json`, `certs/` or database files.

## Commands

```sh
python -m unittest discover tests      # all tests
python run_server.py run               # server (needs config/server.json + certs)
python run_client.py                   # client (needs config/client.json + certs/server.crt)
```

## Git

- Phase 2 work happens on the `phase-2` branch (or short branches made from it and merged back).
- Commit as `shali-mor <shali.mor@gmail.com>`.
