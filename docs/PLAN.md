# Site Filter Proxy — Project Plan

> High-school yearly project. Python, sockets, secure connections, simple database.
> How the system works (diagrams, protocol, database) is in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 1. Goal

Build a site filter: every user who browses through my proxy is checked against my blocklist
database before a site is opened. Every check is logged. The design must be easy to extend later
with an admin dashboard and external blocklist sources.

## 2. Decisions

| # | Topic | Decision |
|---|---|---|
| 1 | Language | Python 3, standard library only |
| 2 | How users connect | My own **client app** on each computer. The browser's proxy setting points to it (`127.0.0.1:8080`). |
| 3 | Server location | A **different machine**. Same local network in Phase 1; the design must also work over the internet later (config change only). |
| 4 | Server's job | **Only answers allow/block** for a site name. It never carries website traffic. The client opens the website itself. |
| 5 | Secure connection | Client ⇄ server over **TLS 1.3** with Python's `ssl` module. Key exchange = **Diffie-Hellman** (ECDHE), built into TLS 1.3. Server certificate is pinned in the client. |
| 6 | Client authentication | Each client has an id + secret token, sent in the first message. |
| 7 | Filtering type | **Blocklist**: everything is allowed except listed sites. Blocking a domain also blocks its subdomains. |
| 8 | Users | **Same rules for everyone.** |
| 9 | What is checked | Once per **new connection** to a site name (not per page or image). |
| 10 | Allowed ports | Client opens websites only on **80 and 443**. |
| 11 | Blocklist source (Phase 1) | `blacklist.txt` file **on the server machine**, imported into SQLite. Not sent over the network. |
| 12 | Logging | **Required.** Every check (allow and block) is written to the database. Basis for the future dashboard. |
| 13 | Server unreachable | Phase 1: **block** (fail closed). Phase 2: use a cached answer saved in the last `offline_grace_seconds` (default 1 hour), even if expired; otherwise block. |
| 14 | Client cache | **Phase 2**, not Phase 1. A `DecisionCache` class inside the client, in front of the server call. The server does not change. |
| 15 | Code & tools | Private GitHub repo `shali-mor/YearlyProject`. Work is split into tickets in **Paperclip**. |
| 16 | When the server is asked (Phase 2) | Only when the cache has no fresh answer (saved less than `cache_seconds` ago) for the cleaned host name. |
| 17 | Cache key and size (Phase 2) | Key = host cleaned with `common.domains.normalize_host`. Expiry `cache_seconds` = **300**. At most `cache_max_entries` = **1000** hosts; the one saved longest ago is removed first. Only real `result` answers are saved. Memory only. |
| 18 | Logging vs. cache (Phase 2) | Accepted trade-off: answers from the cache are **not** in the server's `access_log`. Written in ARCHITECTURE.md, *Known limitations*. `cache_seconds: 0` turns the cache off. |
| 19 | Reconnect (Phase 2) | Waits of 1, 2, 4, 8, 16, 30, 30 … seconds after failed attempts in a row; back to 1 after a successful connection. No background thread. |

## 3. Phases

```mermaid
flowchart LR
    P1["Phase 1<br/>Working filter<br/>on local network"] --> P2["Phase 2<br/>Client cache +<br/>offline fallback"]
    P2 --> P3["Phase 3<br/>Admin dashboard"]
    P3 --> P4["Phase 4<br/>External<br/>blocklist sources"]
    P4 --> P5["Phase 5 (optional)<br/>Server on<br/>the internet"]
```

### Phase 1 — Working filter on the local network

What gets built:
* `common/`: protocol messages and host-name helpers, shared by client and server.
* Server: TLS listener, `hello` login, `check` → allow/block, PolicyEngine, SQLite repository, access log,
  blocklist import, commands `run`, `import`, `add-client`, `logs`.
* Client: local proxy on `127.0.0.1:8080`, request parser (CONNECT and plain HTTP), FilterClient with one
  TLS connection + lock + reconnect, relay, block page, fail-closed when server is unreachable.
* Certificate script, example configs, example `blacklist.txt`, run instructions.
* Unit tests + a two-computer test guide.

**Done when:**
1. On computer X, a browser set to the client can open allowed `http://` and `https://` sites normally.
2. A site in `blacklist.txt` (and its subdomains) is blocked; `http://` shows the block page.
3. Every check appears in `access_log` with time, client, IP, host, decision and matched rule.
4. Stopping the server makes the client block everything with "filter server unavailable"; starting it again recovers without restarting the client.
5. A client with a wrong token is refused and the attempt is logged.
6. Wireshark on connection B shows only TLS 1.3 traffic with a Diffie-Hellman `key_share`.

### Phase 2 — Client cache and offline fallback

The design is in ARCHITECTURE.md, sections 5.4 (offline), 5.6 (cache hit), 11 (settings) and 14 (limitations).

What gets built (client only — server, protocol and database do not change):
* `client/decision_cache.py`: class `DecisionCache` — cleaned host → decision + time saved, own lock,
  fresh lookup, offline lookup, size limit (oldest removed first).
* `FilterClient` uses the cache before asking the server, saves real answers, and uses the offline rule
  when the server can't be reached.
* `FilterClient` reconnects with increasing waits (1 → 30 seconds) instead of a fixed 5 seconds.
* New optional settings in `config/client.json`: `cache_seconds`, `offline_grace_seconds`, `cache_max_entries`
  (and in `config/client.example.json`).
* Unit tests for the cache and the waits (using a fake clock, so tests don't sleep), and an updated test guide.

**Done when:**
1. Opening the same site twice within 5 minutes sends **one** `check` to the server (one `access_log` row).
2. After 5 minutes the server is asked again.
3. Server stopped: a site checked in the last hour still opens (or stays blocked if it was blocked);
   a site never checked is blocked with "filter server unavailable".
4. Server stopped: the client's connection attempts are spaced 1, 2, 4 … up to 30 seconds apart; after the
   server is started again, the client recovers without a restart and the wait is back to 1 second.
5. `cache_seconds: 0` gives exactly the Phase 1 behavior.
6. All Phase 1 "Done when" items still pass; `python -m unittest discover tests` is green.
7. Security review of Phase 2 has no critical or high findings.

### Phase 3 — Admin dashboard
* Runs on the server machine, uses the same Repository.
* Views: latest checks, most blocked sites, activity per client, search by site/time.
* Edit the blocklist from the dashboard (adds a `manual` source).
* Admin login (new `admins` table, passwords hashed with salt).

### Phase 4 — External blocklist sources
* New `RuleSource` types, e.g. download a public category list from a URL.
* Each source has its own row in `sources` and can be refreshed or removed as a group.
* Categories (social, games, …) shown in the dashboard.

### Phase 5 (optional) — Server on the internet
* Public address / port forwarding, certificate for the public host name.
* Rate limiting and lockout after repeated failed logins.

## 4. Phase 1 tickets (Paperclip)

| # | Ticket | Agent | Depends on |
|---|---|---|---|
| 1 | Review ARCHITECTURE.md and PLAN.md; write `common/protocol.py` + `common/domains.py` skeleton and folder layout | CTO | — |
| 2 | Certificate script, example configs, `.gitignore`, example `blacklist.txt`, README run instructions | DevOps | 1 |
| 3 | Server: TLSServer, Protocol, Auth, `python -m server run` | Backend | 1 |
| 4 | Server: Repository (SQLite), schema, PolicyEngine, AccessLogger, Importer, `import` / `add-client` / `logs` commands | Backend 2 | 1 |
| 5 | Client: LocalProxy, RequestParser, FilterClient, Relay, block page, fail-closed | Backend | 1, 3 |
| 6 | Security review of TLS setup, pinning, token handling, input limits, port allowlist | Security | 3, 4, 5 |
| 7 | Unit tests + two-computer test guide; check all "Done when" items | QA | 3, 4, 5 |

Working rules for the tickets:
* ARCHITECTURE.md is the source of truth. A change to the design is made in the document first, then in the code.
* Standard library only. Small, readable functions with comments — the code must be explainable in a presentation.
* Each ticket ends with a commit that describes what was done.

### Phase 1 status (2026-11-07)

Phase 1 code was written directly (not through Paperclip tickets). Tested on one computer
(server and client both on 127.0.0.1):

| "Done when" item | Status |
|---|---|
| 1. Allowed `http://` and `https://` sites open | ✅ tested (example.com, ynet.co.il) |
| 2. Blocked site and subdomains blocked, block page for `http://` | ✅ tested (facebook.com, neverssl.com) |
| 3. Every check in `access_log` | ✅ tested (`python run_server.py logs`) |
| 4. Server down → block all, recovers without restarting client | ✅ tested |
| 5. Wrong token refused and logged | ✅ tested |
| 6. Wireshark shows TLS 1.3 with Diffie-Hellman `key_share` | ✅ recorded with `tools/capture_tap.py` → `docs/wireshark/` (Client/Server Hello key_share = x25519, then only Application Data) |
| Server reached over the network IP (10.0.0.24), certificate for that IP | ✅ tested (same Mac; the client used the network address, not 127.0.0.1) |
| Two physically different computers | ⏳ for the student to do with the guide in [TESTING.md](TESTING.md), section 3 |
| Security review | ✅ done — added login timeout, max clients, safe logging of client text |
| Presentation | ✅ slide deck (see the project's chat / artifacts) |

**Phase 1 is complete.** Phase 2 continues on the `phase-2` branch, run by the Paperclip team.

## 4b. Phase 2 tickets (Paperclip)

| Ticket | What | Agent | Depends on |
|---|---|---|---|
| SHA-95 | Phase 2 design in ARCHITECTURE.md and PLAN.md (this change) | CTO | — |
| SHA-96 | Client: `DecisionCache` + offline fallback in `FilterClient`, new settings, tests | Backend | SHA-95 |
| SHA-97 | Client: reconnect with increasing waits, tests | Backend | SHA-95 |
| SHA-98 | QA: test Phase 2 end to end, update TESTING.md, check the "Done when" items | QA | SHA-96, SHA-97 |
| SHA-99 | Security review of Phase 2 | Security | SHA-96, SHA-97 |

SHA-96 and SHA-97 both change `client/filter_client.py`: keep each change small and merge one before
starting the other's final merge, to avoid conflicts.

## 5. Open questions

_None right now._ New questions are added here and decided before the related ticket starts.
