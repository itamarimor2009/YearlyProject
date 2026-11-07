# Site Filter Proxy — Architecture

> This document describes **how the system works**. It is the technical basis of the project.
> The phases, tasks and decisions are in [PLAN.md](PLAN.md).

---

## 1. The idea in one sentence

Every website the browser tries to open first goes to a small **client app** on the user's computer.
The client asks a **filter server** (on another machine) *"is this site allowed?"*. The server checks
its **blocklist database**, writes a **log entry**, and answers **allow** or **block**. The client then
opens the site or shows a block page.

---

## 2. The big picture

```mermaid
flowchart LR
    subgraph PC["User's computer"]
        B["Web browser<br/>proxy setting = 127.0.0.1:8080"]
        C["Client app<br/>(Python)"]
    end

    subgraph SRV["Server machine"]
        S["Filter server<br/>(Python)"]
        DB[("SQLite<br/>blocklist + logs")]
        F["blacklist.txt"]
    end

    W["Websites<br/>(internet)"]

    B -- "A: every request" --> C
    C == "B: TLS 1.3 (Diffie-Hellman)<br/>check host → allow/block" ==> S
    S --> DB
    F -. "import" .-> DB
    C -- "C: only if allowed" --> W
```

**Important:** the server **never touches website traffic**. It only receives a *site name* and returns a *decision*.
The client opens the connection to the website itself.

---

## 3. The three connections (and their ports)

```mermaid
flowchart LR
    B["Browser"] -- "A<br/>port 8080<br/>plain, localhost only" --> C["Client app"]
    C == "B<br/>port 9443<br/>encrypted TLS" ==> S["Filter server"]
    C -- "C<br/>port 80 or 443<br/>taken from the browser's request" --> W["Website"]
```

| | Connection | Port | Who decides the port | Encrypted? |
|---|---|---|---|---|
| **A** | Browser → Client app | `8080` | You, in the browser's proxy settings | No (never leaves the computer) |
| **B** | Client app → Filter server | `9443` | You, in the config files | **Yes — TLS 1.3** |
| **C** | Client app → Website | `80` / `443` | The browser (`http://` = 80, `https://` = 443) | HTTPS sites: yes, end-to-end between browser and site |

* Only the **site name** travels on B. The port of C is never sent to the server.
* The client allows only ports **80 and 443** on C. Any other port is refused.

---

## 4. Components

```mermaid
flowchart TB
    subgraph CLIENT["Client app"]
        LP["LocalProxy<br/>listens on 127.0.0.1:8080<br/>one thread per browser connection"]
        RQ["RequestParser<br/>reads CONNECT / GET line<br/>→ host + port"]
        FC["FilterClient<br/>one TLS connection to server<br/>check(host) → allow/block"]
        DC["DecisionCache (Phase 2)<br/>cleaned host → decision + time"]
        RL["Relay<br/>copies bytes browser ⇄ website"]
        BP["Block page"]
        LP --> RQ --> FC
        FC <--> DC
        FC -- allow --> RL
        FC -- block --> BP
    end

    subgraph SERVER["Filter server"]
        TS["FilterServer<br/>listens on 0.0.0.0:9443<br/>one thread per client"]
        PR["Protocol<br/>hello / check / ping"]
        AU["Auth<br/>checks client token"]
        PE["PolicyEngine<br/>check(host) → Decision"]
        RP["Repository (interface)<br/>SQLite implementation"]
        LG["AccessLogger"]
        IM["Importer<br/>blacklist.txt → DB"]
        TS --> PR --> AU
        PR --> PE --> RP
        PE --> LG --> RP
        IM --> RP
    end

    FC == TLS ==> TS
```

### Client app

| Part | Job |
|---|---|
| **LocalProxy** | Accepts connections from the browser on `127.0.0.1:8080`. Starts a thread for each one. |
| **RequestParser** | Reads the first line the browser sends and gets the `host` and `port`. |
| **FilterClient** | Keeps **one TLS connection** to the server. `check(host)` sends a question and **waits on the socket** for the answer. A lock makes sure only one question at a time travels on the socket. If the connection drops, it reconnects, waiting longer after each failure (see section 5.4). |
| **DecisionCache** (Phase 2) | Remembers the server's last answer for each cleaned host name, with the time it was saved. `FilterClient` looks here **before** asking the server. (`client/decision_cache.py`, rules in section 5.6) |
| **Relay** | When the site is allowed, opens connection C to the website and copies bytes in both directions until one side closes. |
| **Block page** | When the site is blocked, sends the browser `403 Forbidden` (and an HTML page for `http://` sites). |

### Filter server

| Part | Job |
|---|---|
| **FilterServer** | Accepts TLS connections from clients on port `9443`. One thread per client. (`server/tls_server.py`) |
| **Protocol** | Reads and writes the JSON-line messages (see section 6). |
| **Auth** | The first message must be `hello` with a valid client token, otherwise the connection is closed. |
| **PolicyEngine** | Decides allow/block for a host (see section 7). Does **not** know about sockets or SQL. |
| **Repository** | The only part that talks to the database. Defined as an interface, implemented with SQLite. |
| **AccessLogger** | Writes one row per `check` into `access_log`. |
| **Importer** | Loads `blacklist.txt` into the database. |

**Layering rule:** sockets → protocol → policy → repository → database. Each layer only calls the one below it.
This is what lets us add a dashboard or external blocklist sources later without changing the network code.

---

## 5. Request flows

### 5.1 Client start-up (TLS handshake + login)

```mermaid
sequenceDiagram
    participant C as Client app
    participant S as Filter server
    C->>S: TCP connect to port 9443
    C->>S: TLS ClientHello (with Diffie-Hellman key share)
    S->>C: TLS ServerHello (with Diffie-Hellman key share) + certificate
    Note over C: Checks the certificate against the pinned server.crt
    Note over C,S: Both sides now share a secret key. Everything below is encrypted.
    C->>S: hello (client_id, token)
    S->>C: hello_ok
    Note over C: Ready. Start listening for the browser on 8080.
```

### 5.2 Allowed HTTPS site

```mermaid
sequenceDiagram
    participant B as Browser
    participant C as Client app
    participant S as Filter server
    participant DB as SQLite
    participant W as www.ynet.com
    B->>C: CONNECT www.ynet.com:443
    C->>S: check www.ynet.com
    S->>DB: is www.ynet.com or ynet.com blocked?
    DB-->>S: no
    S->>DB: write log row (allow)
    S-->>C: result allow
    C->>W: open TCP connection to port 443
    C-->>B: HTTP/1.1 200 Connection Established
    B->>W: encrypted HTTPS traffic (relayed by the client)
    W->>B: encrypted HTTPS traffic (relayed by the client)
```

### 5.3 Blocked site

```mermaid
sequenceDiagram
    participant B as Browser
    participant C as Client app
    participant S as Filter server
    participant DB as SQLite
    B->>C: CONNECT www.facebook.com:443
    C->>S: check www.facebook.com
    S->>DB: is www.facebook.com or facebook.com blocked?
    DB-->>S: yes, rule facebook.com
    S->>DB: write log row (block)
    S-->>C: result block
    C-->>B: HTTP/1.1 403 Forbidden
    Note over C: No connection to facebook.com is ever opened
```

### 5.4 Server not reachable (Phase 2: offline fallback)

```mermaid
sequenceDiagram
    participant B as Browser
    participant C as Client app
    participant DC as DecisionCache
    participant S as Filter server
    B->>C: CONNECT www.ynet.com:443
    C->>DC: fresh answer for www.ynet.com?
    DC-->>C: no (never asked, or older than 5 minutes)
    C-xS: check www.ynet.com (no answer within 3 seconds)
    C->>DC: any answer saved in the last hour?
    alt yes, saved answer is allow
        DC-->>C: allow
        C-->>B: HTTP/1.1 200 Connection Established
    else yes, saved answer is block
        DC-->>C: block
        C-->>B: HTTP/1.1 403 Forbidden
    else no usable answer
        DC-->>C: nothing
        Note over C: Fail closed: when in doubt, block
        C-->>B: 503 "Filter server unavailable"
    end
    Note over C: Next connection attempt only after the waiting time (1, 2, 4 ... 30 seconds)
```

**Offline rule:** when the server can't be reached, the client may use a cached answer **even if it is
expired**, as long as it was saved at most `offline_grace_seconds` ago (default **3600** = 1 hour).
If there is no such answer, the site is **blocked** with `503`, exactly like in Phase 1.

**Reconnect with increasing waits.** Phase 1 waited a fixed 5 seconds after a failed connection.
Phase 2 waits longer after each failure in a row: **1, 2, 4, 8, 16, 30, 30, …** seconds (doubled each time,
never more than 30). After a **successful** connection the wait goes back to 1 second.

* There is no background thread: the client tries to connect when a browser request needs the server
  and the waiting time is over.
* While the client is waiting, a request does not touch the network at all. It goes straight to the offline
  rule above, so the browser gets an answer immediately instead of after a 3-second timeout.
* If an *open* connection breaks in the middle of a check, the client reconnects once right away
  (the server may simply have closed an idle connection). Only a *failed connection attempt* starts the waits.
* Why increasing waits: a server that is down for a long time is not hammered with connection attempts,
  but a short break (for example a server restart) is still noticed within a second or two.

### 5.5 One page, many sites

Opening `www.ynet.com` makes the browser load pieces from many site names (images, scripts, ads).

```mermaid
flowchart LR
    U["You open www.ynet.com"] --> P1["www.ynet.com"]
    U --> P2["images.ynet.com"]
    U --> P3["cdn.example.net"]
    U --> P4["ads.example.com"]
    P1 --> K["Client: one check<br/>per new connection"]
    P2 --> K
    P3 --> K
    P4 --> K
    K --> S["Server"]
```

* Pages and images on the **same site name** reuse the browser's connection, so there is **no extra check**.
  For HTTPS the client cannot even see the paths (they are encrypted).
* Each **different site name** is checked once per connection. This means a blocked site is also blocked
  when it is embedded inside another site.
* For plain `http://` the client forces one request per connection (`Connection: close`), so every request
  is checked against the right host.
* From Phase 2, "one check" first looks in the client's cache (section 5.6). So the server is asked about
  `images.ynet.com` only the first time in 5 minutes, not for every new connection.

### 5.6 Answer from the cache (Phase 2)

**The rule in one sentence:** the client asks the server only when its cache has no *fresh* answer
(saved less than `cache_seconds` ago) for the cleaned host name.

```mermaid
sequenceDiagram
    participant B as Browser
    participant C as Client app
    participant DC as DecisionCache
    participant S as Filter server
    B->>C: CONNECT www.ynet.com:443
    C->>DC: fresh answer for www.ynet.com?
    DC-->>C: yes, allow (saved 40 seconds ago)
    Note over C,S: The server is not asked, so no access_log row is written
    C-->>B: HTTP/1.1 200 Connection Established
```

How the cache works (`client/decision_cache.py`, class `DecisionCache`, used only by `FilterClient`):

| Question | Answer |
|---|---|
| What is the key? | The **cleaned host name** from `common.domains.normalize_host` (lowercase, no trailing dot, IDNA). So `WWW.Ynet.com.` and `www.ynet.com` share one entry. A host that `normalize_host` rejects is never cached; it is sent to the server as in Phase 1 (which answers `error` → block). |
| What is stored? | The decision (`allow` or `block`) and the time it was saved. |
| Which answers are saved? | Only real `result` answers from the server. An `error` reply or "server unavailable" is **never** saved. |
| When is an answer fresh? | When it was saved less than `cache_seconds` ago (default **300** = 5 minutes). A fresh answer is used without asking the server. |
| When can an old answer still be used? | Only when the server is unreachable, and only if it was saved less than `offline_grace_seconds` ago (default **3600**), see section 5.4. |
| How big can it get? | At most `cache_max_entries` hosts (default **1000**). When it is full, the entry that was **saved longest ago is removed first**. Saving a host again counts as new. |
| When are entries deleted? | When they are too old even for offline use (older than `offline_grace_seconds`), or pushed out because the cache is full. |
| Threads? | Many browser connections run at the same time, so the cache has its **own lock**. A cache hit does not need the socket lock, so it never waits behind a slow server question. |
| Turning it off | `cache_seconds: 0` means nothing is saved: every check asks the server and the offline fallback is off (Phase 1 behavior). Useful for tests and the demo. |

The client writes a short line to its own log for each cache answer (e.g. `www.ynet.com allow (cache)`),
so a cache answer can still be seen while testing.

---

## 6. Protocol on connection B

* Runs **inside TLS**.
* Each message is **one line of JSON**, UTF-8, ending with `\n`.
* Maximum line length: **4096 bytes**. Longer lines → error and disconnect.
* Every request has an `id`; the reply carries the same `id`.

| Direction | Message | Example |
|---|---|---|
| C → S | `hello` | `{"type":"hello","version":1,"client_id":"pc-12","token":"…"}` |
| S → C | `hello_ok` | `{"type":"hello_ok"}` |
| C → S | `check` | `{"type":"check","id":7,"host":"www.ynet.com"}` |
| S → C | `result` | `{"type":"result","id":7,"decision":"allow","rule":null}` |
| S → C | `result` | `{"type":"result","id":8,"decision":"block","rule":"facebook.com"}` |
| C → S | `ping` | `{"type":"ping","id":9}` — "are you there?" (the server supports it; the client doesn't need it, because it reconnects automatically) |
| S → C | `pong` | `{"type":"pong","id":9}` |
| S → C | `error` | `{"type":"error","id":7,"code":"bad_request","message":"…"}` |

Error codes: `unauthorized`, `bad_request`, `too_long`, `unsupported_version`, `internal`.

Rules:
1. The first message must be `hello`. Anything else → `error unauthorized` and disconnect.
2. A bad `hello` → `error unauthorized` and disconnect (and a log line on the server).
3. The server never sends a message the client did not ask for.

---

## 7. How the server decides

```mermaid
flowchart TB
    A["check(host)"] --> N["Normalize:<br/>lowercase, remove trailing dot,<br/>convert non-English names (IDNA)"]
    N --> V{"Valid host name?"}
    V -- no --> E["error bad_request"]
    V -- yes --> L["Make candidates:<br/>a.b.ynet.com → a.b.ynet.com, b.ynet.com, ynet.com"]
    L --> Q{"Any candidate<br/>in blocked_sites?"}
    Q -- yes --> BL["block<br/>(rule = matched domain)"]
    Q -- no --> AL["allow<br/>(default policy)"]
    BL --> LOG["Write access_log row"]
    AL --> LOG
```

* Blocking `facebook.com` also blocks `www.facebook.com`, `m.facebook.com`, and every other subdomain.
* Blocking `m.facebook.com` does **not** block `www.facebook.com`.
* Default policy: **allow** (it's a blocklist).
* IP addresses (e.g. `142.250.1.1`) are matched exactly.

---

## 8. Database (SQLite)

```mermaid
erDiagram
    sources ||--o{ blocked_sites : "provides"
    clients ||--o{ access_log : "makes"

    sources {
        int id PK
        text name "e.g. file:blacklist.txt"
        text kind "file (later: url, manual)"
        text last_imported
    }
    blocked_sites {
        int id PK
        text domain "e.g. facebook.com"
        int source_id FK
        text category "optional, e.g. social"
        int enabled "1 or 0"
        text added_at
    }
    clients {
        int id PK
        text client_id "e.g. pc-12"
        text token_hash "SHA-256 of the token"
        int enabled "1 or 0"
        text created_at
    }
    access_log {
        int id PK
        text ts "time of the check"
        text client_id
        text client_ip
        text host
        text decision "allow or block"
        text rule "matched blocked domain, null when allowed"
    }
```

* `blocked_sites` has a unique key on `(domain, source_id)` and an index on `domain`.
* `access_log` has indexes on `ts` and `host` (the future dashboard will search by these).
* `access_log.rule` stores the matched domain as **text** (not a link to `blocked_sites`), so old log rows
  stay correct even after the blocklist is imported again.
* The schema version is stored with `PRAGMA user_version`, so later phases can upgrade the database safely.
* Every thread opens its **own** SQLite connection. All SQL uses `?` placeholders (no SQL injection).

---

## 9. The blocklist file

`data/blacklist.txt` lives **on the server machine only**.

```text
# Social networks
facebook.com
instagram.com
tiktok.com

# Games
example-games.com
```

* One domain per line. `#` starts a comment. Empty lines are ignored.
* Lines that are not valid domain names are skipped and reported.
* Importing **replaces** everything that came from this file (it is the source of truth for the `file:blacklist.txt` source).
* Import runs at server start-up and with the command `python run_server.py import`.
  The server reads the database on each check, so changes take effect immediately on the server.
  Clients may still use a cached answer for up to `cache_seconds` (5 minutes) — see section 14.

---

## 10. Security

| Threat | Protection |
|---|---|
| Someone reads the traffic on B | TLS 1.3. The key is agreed with **ephemeral Diffie-Hellman** (ECDHE, X25519), so even a stolen server key can't decrypt old traffic. |
| Someone pretends to be the server (man-in-the-middle) | The server has a certificate. The client trusts **only** that certificate (`server.crt` pinned in the client) and checks the host name. Diffie-Hellman alone does not stop this; the certificate does. |
| A stranger uses the server | Every client must send a valid **token** in `hello`. Tokens are random, stored only as SHA-256 hashes, and compared with `hmac.compare_digest`. |
| The client is used as an open proxy by others | The client listens on `127.0.0.1` only. |
| The client is used to reach non-web services | Connection C allows only ports 80 and 443. |
| Bad or huge input | Max line length, JSON validation, host name validation, socket timeouts. |
| Slow or too many connections (tying up the server) | A new client must finish TLS + login within **10 seconds**; at most **100** clients at the same time. |
| Fake lines in the server log | Text from the client (like a wrong `client_id`) is logged with `repr()`, so new-line characters can't create fake log lines. |
| SQL injection | `?` placeholders only. |
| Private key leaks | `server.key` stays on the server machine, is never committed to git, and has file permissions 600. |

Both sides ask for the **X25519** group explicitly (`common/tls_settings.py`). Without this, new OpenSSL
versions pick a *hybrid* method (X25519 mixed with the post-quantum ML-KEM), which is harder to explain.

How to show the Diffie-Hellman key exchange in the project presentation:
* the client and server print it when connecting, e.g. `TLSv1.3, key exchange x25519, cipher TLS_AES_256_GCM_SHA384`;
* capture connection B in **Wireshark** and point to the `key_share` field in ClientHello/ServerHello
  (step-by-step guide, and a capture tool that needs no admin rights: [TESTING.md](TESTING.md), section 4).

---

## 11. Configuration

`config/server.json`
```json
{
  "listen_host": "0.0.0.0",
  "listen_port": 9443,
  "cert_file": "certs/server.crt",
  "key_file": "certs/server.key",
  "db_file": "data/filter.db",
  "blacklist_file": "data/blacklist.txt",
  "log_file": "data/server.log"
}
```

`config/client.json`
```json
{
  "local_port": 8080,
  "server_host": "192.168.1.50",
  "server_port": 9443,
  "server_cert": "certs/server.crt",
  "client_id": "pc-12",
  "token": "…",
  "check_timeout_seconds": 3,
  "allowed_ports": [80, 443],
  "cache_seconds": 300,
  "offline_grace_seconds": 3600,
  "cache_max_entries": 1000
}
```

The last three settings are new in Phase 2 and **optional**: if one is missing, the client uses the
default shown above. `offline_grace_seconds` should be at least `cache_seconds`; a smaller value is
raised to `cache_seconds` (otherwise a fresh answer could be "too old" for offline use).

The server certificate is created once with a script (`scripts/make_cert.sh`). Its *Subject Alternative Name*
must contain the server's IP address or host name, otherwise the client will reject it.
Moving the server to the internet later means: new address in `client.json` + a new certificate. No code changes.

---

## 12. Folder layout

```text
YearlyProject/
├── docs/
│   ├── ARCHITECTURE.md      ← this file
│   └── PLAN.md
├── run_server.py            # python run_server.py run | import | add-client | logs
├── run_client.py            # python run_client.py
├── common/                  # shared by client and server
│   ├── config.py            # read a JSON settings file
│   ├── protocol.py          # encode/decode messages, limits, error codes
│   ├── domains.py           # normalize host, build candidate domains
│   └── tls_settings.py      # TLS 1.3 + X25519 Diffie-Hellman settings
├── client/
│   ├── local_proxy.py       # LocalProxy + request parsing
│   ├── filter_client.py     # FilterClient (TLS, lock, reconnect with increasing waits)
│   ├── decision_cache.py    # DecisionCache: host → decision, expiry, offline grace (Phase 2)
│   ├── relay.py             # copy bytes both ways with select()
│   └── block_page.html
├── server/
│   ├── tls_server.py        # FilterServer: TLS + protocol + login
│   ├── policy.py            # PolicyEngine
│   ├── access_logger.py
│   ├── importer.py          # source → database
│   ├── storage/
│   │   ├── base.py          # Repository interface
│   │   ├── sqlite_repo.py
│   │   └── schema.sql
│   └── sources/
│       ├── base.py          # RuleSource interface
│       └── blocklist_file.py
├── config/
│   ├── server.example.json
│   └── client.example.json
├── data/
│   └── blacklist.txt        # example list
├── certs/                   # generated; keys are git-ignored
├── scripts/
│   └── make_cert.sh
├── tools/
│   └── capture_tap.py       # demo: record connection B into a Wireshark file
└── tests/
```

Only the Python standard library is used: `socket`, `ssl`, `threading`, `select`, `sqlite3`, `json`, `hashlib`, `hmac`, `secrets`, `logging`.
Run everything from the project folder (no `pip install` needed).

---

## 13. How the design grows later

```mermaid
flowchart TB
    subgraph NOW["Phase 1"]
        FILE["blacklist.txt"] --> IMP["Importer"]
        IMP --> REPO["Repository"]
        PE["PolicyEngine"] --> REPO
        REPO --> DB[("SQLite")]
    end

    subgraph P2["Phase 2 (client only)"]
        FC["FilterClient"] --> CACHE["DecisionCache<br/>expiry + offline grace"]
        FC --> BACK["Reconnect with<br/>increasing waits"]
    end

    subgraph LATER["Later phases (new code only, nothing above changes)"]
        DASH["Admin dashboard<br/>logs, charts, edit blocklist<br/>(Phase 3)"]
        EXT["External sources<br/>public category lists<br/>(Phase 4)"]
    end

    FC == "check over TLS<br/>(only on a cache miss)" ==> PE
    DASH --> REPO
    EXT --> IMP
```

| Future feature | Where it plugs in |
|---|---|
| Client cache (Phase 2) | New class `DecisionCache` (`client/decision_cache.py`), used by `FilterClient` in front of the server call. The server, the protocol and the database **do not change**. |
| Reconnect with increasing waits (Phase 2) | Inside `FilterClient` only: the fixed 5-second wait becomes 1, 2, 4 … 30 seconds. |
| Admin dashboard | A new program on the server machine that uses the same `Repository` to read `access_log` and edit `blocked_sites`. |
| External blocklist sources | A new `RuleSource` subclass (e.g. download a public list). Each source gets its own row in `sources`, so it can be refreshed or removed as a group. |
| Different database | A new `Repository` implementation. |

---

## 14. Known limitations

* A user who changes the browser's proxy setting can skip the filter. (True for any proxy-based filter without system-level control.)
* For blocked **HTTPS** sites the browser shows its own error, not our block page, because we do not decrypt HTTPS.
* Filtering is by **site name only**, not by page or content.
* A site opened by its **IP address** (e.g. `https://157.240.1.35`) is only blocked if that IP is in the list.
* Same rules for everyone (by decision).
* **Cached answers are not logged on the server** (Phase 2). When the client answers from its cache, the server
  is not asked, so there is no `access_log` row. The log (and the future dashboard) shows **at most about one
  check per host per client every `cache_seconds`**, not every visit. This is the price for fewer messages and
  for working while the server is down. Setting `cache_seconds: 0` brings back "every check is logged".
* **Blocklist changes reach clients with a delay** (Phase 2). A site that is newly added to the blocklist can
  stay allowed on a client for up to `cache_seconds` (5 minutes), and up to `offline_grace_seconds` (1 hour)
  while the server is unreachable. Removing a site from the list has the same delay.
* The cache lives only in memory: restarting the client app empties it.
