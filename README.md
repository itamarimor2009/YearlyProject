# Site Filter Proxy

**By Itamar.** A site filter for web browsing, written in Python (standard library only).

Every website a browser tries to open is first checked against **one central blocklist**.
Blocked sites don't open, allowed sites open normally, and **every check is logged**.

```text
 User's computer                                  Server computer
┌───────────────────────────────────┐            ┌─────────────────────────────┐
│  Browser ──A──▶ Client app ───────┼═══B═══════▶│ Filter server ──▶ SQLite    │
│          (127.0.0.1:8080)    │    │  TLS 1.3   │ "allow" / "block"  blocklist│
│                              │    │            │                    + log    │
└──────────────────────────────┼────┘            └─────────────────────────────┘
                               C (only if allowed)
                               ▼
                            Website
```

1. **A:** the browser's proxy setting sends every request to the **client app** on the same computer.
2. **B:** the client asks the **filter server** over an encrypted **TLS 1.3** connection:
   *"is `www.facebook.com` allowed?"* The server looks in its blocklist, writes a log row, and answers.
3. **C:** only if the answer is *allow*, the client opens the website itself.
   The server never sees the pages, only the site names.

---

## Documentation map

Read them in this order:

| Document | What you'll find there |
|---|---|
| **README.md** (this file) | What the project is, how to run it, the commands |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | **How it works**: drawings of the parts, the message flow, the protocol, the database, security |
| [docs/CODE_TOUR.md](docs/CODE_TOUR.md) | **How to read the code**: which file does what, and one request followed step by step through the code. Includes a glossary of terms. |
| [docs/TESTING.md](docs/TESTING.md) | The automatic tests, a manual checklist, the two-computer test, and Wireshark |
| [docs/PLAN.md](docs/PLAN.md) | The decisions that were made, and the phases (what's done and what's next) |
| [docs/wireshark/](docs/wireshark) | A real recording of the encrypted connection, ready to open in Wireshark |

---

## Requirements

* **Python 3.8 or newer.** Nothing to install with pip.
* **openssl**, to create the server certificate once. It comes with macOS and Linux.
  On Windows, use the one included with Git ("Git Bash").

Run every command **from the project folder**.

---

## Quick start: everything on one computer

The fastest way to see it working. The server and the client both run on your computer.

**1. One-time setup**

```sh
sh scripts/make_cert.sh 127.0.0.1                  # the server's certificate (its "ID card")
cp config/server.example.json config/server.json   # the server's settings
python run_server.py add-client pc-12              # register this computer; prints a token
cp config/client.example.json config/client.json   # the client's settings
```

Open `config/client.json` and change two lines:
`"server_host": "127.0.0.1"` and `"token": "<the token that add-client printed>"`.

**2. Start** (two terminal windows):

```sh
python run_server.py run      # window 1: the filter server
python run_client.py          # window 2: the client app
```

The client prints `Connected to filter server ... (TLSv1.3, key exchange x25519, ...)`.

**3. Try it** (a third window):

```sh
curl -I -x http://127.0.0.1:8080 https://example.com        # 200 Connection Established = allowed
curl -I -x http://127.0.0.1:8080 https://www.facebook.com   # 403 Forbidden = blocked
curl    -x http://127.0.0.1:8080 http://neverssl.com        # prints our block page
python run_server.py logs                                   # the log of all checks
```

Or open a browser that uses the filter (Chrome on a Mac; your normal Chrome is not affected):

```sh
open -na "Google Chrome" --args --proxy-server=127.0.0.1:8080 --user-data-dir=/tmp/filter-test
```

Stop the server and client with **Ctrl+C**.

---

## Real setup: server and clients on different computers

### On the server computer

1. **Certificate.** Use the IP address (or name) that the clients will use to reach the server:
   ```sh
   sh scripts/make_cert.sh 192.168.1.50
   ```
   This creates `certs/server.key` (secret, stays on the server) and `certs/server.crt` (copy it to every client).
2. **Settings:** `cp config/server.example.json config/server.json`
3. **Blocklist:** edit `data/blacklist.txt` (one domain per line).
4. **Register each client computer** and write down the token it prints:
   ```sh
   python run_server.py add-client pc-12
   ```
5. **Start:** `python run_server.py run`

   Make sure the firewall allows incoming connections on port **9443**.

### On each client computer

1. Copy the project folder, and copy `certs/server.crt` from the server into `certs/`.
   **Never copy `server.key`.**
2. `cp config/client.example.json config/client.json`, then set `server_host` (the server's IP),
   `client_id` and `token` (from step 4 above).
3. **Start:** `python run_client.py`
4. **Set the browser's proxy** to `127.0.0.1`, port `8080`, for both HTTP and HTTPS:
   * **Mac (Safari, Chrome):** System Settings → Network → Wi-Fi → Details → Proxies →
     turn on *Web proxy (HTTP)* and *Secure web proxy (HTTPS)*.
   * **Windows (Edge, Chrome):** Settings → Network & internet → Proxy → *Manual proxy setup*.
   * **Firefox:** Settings → Network Settings → *Manual proxy configuration*, and tick
     *Also use this proxy for HTTPS*.

The full step-by-step guide, with common problems and their fixes, is in [docs/TESTING.md](docs/TESTING.md), section 3.

---

## What you'll see

| You open | What happens | Why |
|---|---|---|
| `https://www.wikipedia.org` | Opens normally | Not in the blocklist |
| `http://neverssl.com` | Our "Site blocked" page | In the blocklist; plain `http://`, so we can show our own page |
| `https://www.facebook.com` | The browser's own connection error | Blocked. For `https://` sites the browser can't show our page, because the connection is encrypted between the browser and the site. |
| Any site, while the server is stopped | "Filter server unavailable" | **Fail closed**: if the client can't ask, it blocks |

Blocking `facebook.com` also blocks **all its subdomains** (`www.facebook.com`, `m.facebook.com`, ...).

---

## Server commands

| Command | What it does |
|---|---|
| `python run_server.py run` | Load the blocklist and start the server |
| `python run_server.py import` | Load `data/blacklist.txt` again after editing it. Takes effect at once, no restart needed. |
| `python run_server.py add-client <id>` | Register a client and print its token. Run it again to replace a lost token. |
| `python run_server.py logs [count]` | Show the latest checks (default 20). Times are in UTC. |

## Tests

```sh
python -m unittest discover tests
```

31 tests, about 0.2 seconds. Some tests send bad input on purpose, so warnings like
"Refused login" or "skipped line 5" in the output are expected. The last line must be `OK`.

---

## Project files

| Folder / file | What's inside |
|---|---|
| `run_server.py`, `run_client.py` | The two programs you start |
| `common/` | Code shared by both: the message format (protocol), site-name helpers, TLS settings |
| `client/` | The client app: local proxy, connection to the server, byte relay, block page |
| `server/` | The filter server: TLS server, decision logic, database, blocklist import, access log |
| `config/` | Example settings (`*.example.json`). The real ones are not in git, because they contain tokens. |
| `data/blacklist.txt` | The blocklist |
| `scripts/make_cert.sh` | Creates the server certificate |
| `tools/capture_tap.py` | Demo tool: records connection B into a file Wireshark can open |
| `tests/` | The automatic tests |
| `docs/` | All the documentation (see the map above) |

Files that are **never** in git (each computer creates its own): `config/server.json`,
`config/client.json`, `certs/`, and the database and log files in `data/`.
