# Site Filter Proxy — Code Tour

> A guide for **reading and reviewing the code**. It tells you which file does what, follows one
> request through the code step by step, and explains the terms used everywhere.
> For the drawings and the design, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 1. Suggested reading order

The whole project is about 1,500 lines of Python. Read it from the bottom layer up, so that every
file only uses things you have already seen:

| # | File | Lines | Why read it now |
|---|---|---|---|
| 1 | `common/protocol.py` | 100 | The "language" client and server speak. Everything else uses it. |
| 2 | `common/domains.py` | 100 | How a site name is cleaned and how `www.facebook.com` → `facebook.com` works |
| 3 | `common/tls_settings.py` | 27 | The TLS 1.3 + Diffie-Hellman settings (shared by both sides) |
| 4 | `server/storage/schema.sql` | 49 | The 4 database tables |
| 5 | `server/storage/base.py` → `sqlite_repo.py` | 62 + 175 | Everything that touches the database |
| 6 | `server/sources/` + `server/importer.py` | ~100 | How `blacklist.txt` gets into the database |
| 7 | `server/policy.py` | 50 | **The decision**: allow or block |
| 8 | `server/access_logger.py` | 27 | Writing each check to the log |
| 9 | `server/tls_server.py` | 239 | The network part of the server: TLS, login, answering |
| 10 | `run_server.py` | 115 | The server's commands (`run`, `import`, `add-client`, `logs`) |
| 11 | `client/filter_client.py` | 164 | The client's secure connection to the server |
| 12 | `client/local_proxy.py` | 256 | What the browser talks to |
| 13 | `client/relay.py` | 42 | Copying bytes between the browser and the website |
| 14 | `run_client.py` | 45 | Starting the client |
| 15 | `tests/` | ~400 | Each test file shows how one part is used |

`tools/capture_tap.py` is only a demo tool for Wireshark. It is not part of the filter itself.

---

## 2. What each file does

### `common/` (used by both the client and the server)

| File | Main contents | In one sentence |
|---|---|---|
| `config.py` | `load_config(path)` | Reads a JSON settings file into a dictionary. |
| `protocol.py` | `send_message()`, `receive_message()`, `make_error()`, `ProtocolError`, message-type constants | Every message is one line of JSON; these functions send and read such lines safely (with a size limit). |
| `domains.py` | `normalize_host()`, `candidate_domains()`, `is_ip_address()` | Cleans a site name (lowercase, no trailing dot, valid characters) and lists its parent domains. |
| `tls_settings.py` | `use_diffie_hellman()`, `describe_connection()` | Forces TLS 1.3 with X25519 Diffie-Hellman, and prints what a connection uses. |

### `server/`

| File | Main contents | In one sentence |
|---|---|---|
| `tls_server.py` | class `FilterServer`, `hash_token()` | Accepts clients, does the TLS handshake, checks the login, and answers `check` messages. |
| `policy.py` | classes `PolicyEngine`, `Decision` | Decides allow/block for one site name by asking the repository about each candidate domain. |
| `access_logger.py` | class `AccessLogger` | Writes every decision to the `access_log` table and to the server's screen. |
| `importer.py` | `import_source()` | Reads a source of blocked sites and replaces that source's list in the database. |
| `sources/base.py` | class `RuleSource` | The "shape" every blocklist source must have (`name`, `kind`, `read_domains()`). |
| `sources/blocklist_file.py` | class `BlocklistFileSource` | The source that reads `data/blacklist.txt`. |
| `storage/base.py` | class `Repository` | The list of database operations the server may use (no SQL here). |
| `storage/sqlite_repo.py` | class `SqliteRepository` | Those operations written in SQL for SQLite. **The only file with SQL.** |
| `storage/schema.sql` | 4 `CREATE TABLE` commands | The tables `sources`, `blocked_sites`, `clients`, `access_log`. |

### `client/`

| File | Main contents | In one sentence |
|---|---|---|
| `local_proxy.py` | class `LocalProxy`, `read_request_head()`, `parse_connect_target()`, `parse_http_url()`, `rewrite_http_head()` | Listens on `127.0.0.1:8080`, reads what the browser wants, asks the filter, then opens or blocks. |
| `filter_client.py` | class `FilterClient`, `UNAVAILABLE` | Keeps one TLS connection to the server; `check(host)` returns allow, block or unavailable. |
| `relay.py` | `relay()` | Copies bytes in both directions between two sockets until one side closes. |
| `block_page.html` | an HTML page with `{{TITLE}}`, `{{HOST}}`, `{{MESSAGE}}` | The page shown for blocked `http://` sites. |

### Start-up files

| File | What it does |
|---|---|
| `run_server.py` | Reads `config/server.json`, prepares the database, and runs one command: `run`, `import`, `add-client` or `logs`. |
| `run_client.py` | Reads `config/client.json`, connects to the server, and starts the local proxy. |

---

## 3. Following the code

### 3.1 The server starts: `python run_server.py run`

| Step | Where | What happens |
|---|---|---|
| 1 | `run_server.py` → `main()` | Moves into the project folder, reads `config/server.json`. |
| 2 | `SqliteRepository.create_tables()` | Creates the database file and its tables if they don't exist yet (runs `schema.sql`). |
| 3 | `command_run()` → `import_source()` | Loads the blocklist: `BlocklistFileSource.read_domains()` reads the file line by line and cleans each name with `normalize_host()`; then `replace_source_domains()` saves the list. |
| 4 | `FilterServer.__init__()` | Creates the `PolicyEngine`, the `AccessLogger`, and the TLS settings (`create_tls_context()` loads the certificate and private key). |
| 5 | `FilterServer.start()` | Opens a socket on port 9443 and waits (`accept()`). Each new client gets its own thread running `handle_client()`. |

### 3.2 The client starts: `python run_client.py`

| Step | Where | What happens |
|---|---|---|
| 1 | `run_client.py` → `main()` | Reads `config/client.json`. |
| 2 | `FilterClient.__init__()` → `create_tls_context()` | TLS settings that trust **only** `certs/server.crt` (certificate pinning). |
| 3 | `FilterClient.try_connect()` → `connect()` | `socket.create_connection()` opens TCP to the server; `wrap_socket()` does the **TLS handshake** (the Diffie-Hellman key exchange happens here); then sends `hello` with `client_id` + `token` and waits for `hello_ok`. |
| 3s | *server side:* `talk_to_client()` → `do_hello()` → `is_valid_client()` | The server hashes the token with `hash_token()` and compares it with the stored hash using `hmac.compare_digest()`. |
| 4 | `LocalProxy.start()` | Opens a socket on `127.0.0.1:8080` and waits for the browser. Each browser connection gets its own thread running `handle_browser()`. |

### 3.3 The browser opens `https://www.facebook.com` (blocked)

| Step | Where | What happens |
|---|---|---|
| 1 | Browser | Because of the proxy setting, it connects to `127.0.0.1:8080` and sends `CONNECT www.facebook.com:443 HTTP/1.1`. |
| 2 | `LocalProxy.process_request()` → `read_request_head()` | Reads until the empty line that ends the request head. |
| 3 | `parse_connect_target()` | `"www.facebook.com:443"` → host `www.facebook.com`, port `443`. |
| 4 | `process_request()` | Port 443 is in `allowed_ports`, so we continue. |
| 5 | `FilterClient.check()` → `ask()` | Takes the lock, sends `{"type": "check", "id": 2, "host": "www.facebook.com"}` and **waits** for the answer. |
| 6 | *server:* `serve_requests()` → `handle_check()` | Reads the message and calls the policy. |
| 7 | *server:* `PolicyEngine.check()` | `normalize_host()` cleans the name; `candidate_domains()` gives `["www.facebook.com", "facebook.com"]`; `repository.is_blocked()` is asked about each one. `facebook.com` is in the table → `Decision(host, "block", rule="facebook.com")`. |
| 8 | *server:* `AccessLogger.log_check()` → `add_log()` | One row is written to `access_log`. |
| 9 | *server:* `handle_check()` | Sends `{"type": "result", "id": 2, "decision": "block", "rule": "facebook.com"}`. |
| 10 | `FilterClient.ask()` | The reply has the same `id`, and the decision is `block` → returns `BLOCK`. |
| 11 | `LocalProxy.send_page()` | Sends `403 Forbidden` to the browser and closes. **No connection to facebook.com is ever opened.** |

### 3.4 The browser opens `https://www.wikipedia.org` (allowed)

Steps 1–10 are the same, but the server finds nothing in the blocklist and answers `allow`. Then:

| Step | Where | What happens |
|---|---|---|
| 11 | `process_request()` | `socket.create_connection(("www.wikipedia.org", 443))` opens **connection C** to the website. |
| 12 | `process_request()` | Sends `HTTP/1.1 200 Connection Established` to the browser, meaning "the tunnel is ready". |
| 13 | `relay()` | Copies bytes in both directions using `select()`. The browser and Wikipedia talk encrypted HTTPS through us; the client can't read it and doesn't need to. |

For a plain `http://` site the difference is in step 3 (`parse_http_url()` instead of
`parse_connect_target()`) and step 12: `rewrite_http_head()` turns
`GET http://site/page` into `GET /page` and the request is sent to the website.

### 3.5 The server is down

| Step | Where | What happens |
|---|---|---|
| 1 | `FilterClient.check()` | There is no connection, so it tries `connect()`. It fails (`Connection refused` or a 3-second timeout). |
| 2 | `check()` | Remembers the time of the failure and returns `UNAVAILABLE`. For the next **5 seconds** (`RETRY_WAIT_SECONDS`) it returns `UNAVAILABLE` right away, without trying, so the browser isn't kept waiting. |
| 3 | `process_request()` | Sends `503 "Filter server unavailable"`: **fail closed**. |
| 4 | Later, the next `check()` | After the 5 seconds it tries again. When the server is back, it reconnects and logs in, and sites work again with no restart. |

---

## 4. Design ideas worth noticing

* **Layers.** sockets → protocol → policy → repository → database. Each layer only calls the one
  below it. The network code never writes SQL, and the `PolicyEngine` knows nothing about sockets.
  This is why a dashboard or new blocklist sources can be added later without touching the network code.
* **"Interfaces" with plain base classes.** `Repository` and `RuleSource` list the methods a class must
  have; each method raises `NotImplementedError` until a real class (like `SqliteRepository`) writes it.
* **One connection, one lock.** The browser opens many connections at once (many threads), but they all
  share the client's single TLS connection to the server. `FilterClient.lock` lets only one question at a
  time travel on it, and every reply carries the same `id` as its question.
* **Fail closed.** When in doubt (no answer, a strange answer, an error), the client blocks.
* **Never trust input from the network.** Every message has a size limit (4096 bytes), every socket has a
  timeout, every site name is validated, and SQL always uses `?` placeholders.

---

## 5. "Where do I change...?"

| I want to... | Change this |
|---|---|
| Block or unblock a site | `data/blacklist.txt`, then `python run_server.py import` |
| Change the server's port | `listen_port` in `config/server.json` **and** `server_port` in every `config/client.json` |
| Change the browser port (8080) | `local_port` in `config/client.json`, and the browser's proxy setting |
| Allow other website ports | `allowed_ports` in `config/client.json` |
| Change how long the client waits for an answer | `check_timeout_seconds` in `config/client.json` |
| Change the block page's look | `client/block_page.html` |
| Change how names are matched | `candidate_domains()` in `common/domains.py` |
| Add a new kind of blocklist source | A new class that inherits from `RuleSource` (see `server/sources/blocklist_file.py`) |
| Use another database | A new class that inherits from `Repository` (see `server/storage/sqlite_repo.py`) |

---

## 6. Glossary

| Term | Meaning in this project |
|---|---|
| **Proxy** | A program that the browser sends its requests to, instead of going to websites directly. Our client app is a proxy. |
| **Client app** | Our program on the user's computer (`run_client.py`). It is the browser's proxy and asks the server about each site. |
| **Filter server** | Our program on the server computer (`run_server.py`). It holds the blocklist and decides. |
| **Socket** | One end of a network connection. A program reads and writes bytes on it. |
| **Port** | A number that tells which program on a computer gets the data (8080 = our proxy, 9443 = our server, 443 = HTTPS websites). |
| **127.0.0.1** | "This same computer". A connection to it never leaves the computer. |
| **Host name / site name** | The name in the address, like `www.facebook.com`. |
| **Subdomain / parent domain** | `www.facebook.com` is a subdomain of `facebook.com`; `facebook.com` is its parent. |
| **`CONNECT`** | What a browser sends to a proxy for an `https://` site: "open a tunnel to this site and port". |
| **TLS 1.3** | The standard way to encrypt a connection (the "S" in HTTPS). We use it on connection B. |
| **Handshake** | The first messages of a TLS connection, where both sides agree on the encryption key. |
| **Diffie-Hellman (X25519)** | The method TLS 1.3 uses to agree on a secret key: each side sends a *public* key, and both compute the *same* secret, which is never sent. |
| **Certificate** | The server's "ID card" (`server.crt`), signed with its private key (`server.key`). |
| **Certificate pinning** | The client trusts only our own `server.crt`, so a fake server can't pretend to be ours. |
| **Token** | A long random password that each client computer uses to log in to the server. |
| **Hash (SHA-256)** | A one-way "fingerprint" of a text. The server stores only the token's hash, so the database doesn't reveal the token. |
| **JSON line** | One message = one line of JSON text ending with `\n`. That's our protocol. |
| **Repository** | The part of the server that talks to the database. |
| **Blocklist** | The list of blocked sites. Everything not on it is allowed. |
| **Access log** | The `access_log` table: one row for every check (time, client, IP, site, result, rule). |
| **Fail closed** | If the filter can't decide (for example, the server is down), block rather than allow. |
| **Thread** | A part of a program that runs at the same time as other parts. Each browser connection and each client gets one. |
| **Lock** | Makes threads take turns, so two of them don't use the same connection at the same time. |
| **SQLite** | A small database that is just one file (`data/filter.db`). Built into Python. |
| **SQL injection** | An attack where user text changes an SQL command. Prevented by `?` placeholders. |
| **Wireshark** | A program that shows the packets travelling on the network. Used to show that connection B is encrypted. |
