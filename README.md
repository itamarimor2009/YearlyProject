# Site Filter Proxy

A high-school yearly project: a site filter for web browsing, written in Python.

Every site the browser opens first goes to a small **client app** on the user's computer.
The client asks a **filter server** (on another computer) over a secure **TLS 1.3** connection
(Diffie-Hellman key exchange) whether the site is allowed. The server checks its **blocklist**
(SQLite database), writes a **log entry**, and answers *allow* or *block*.

* How it works (with drawings): [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
* Decisions and phases: [docs/PLAN.md](docs/PLAN.md)

## Requirements

* Python 3.8 or newer. No extra packages (only the standard library).
* `openssl` (to create the server certificate once). It comes with macOS and Linux;
  on Windows, use the one included with Git ("Git Bash").

Run all commands **from the project folder**.

---

## 1. Set up the server computer

**a. Create the certificate.** Use the IP address (or name) that the clients will use to reach the server:

```sh
sh scripts/make_cert.sh 192.168.1.50
```

This creates `certs/server.key` (secret, stays here) and `certs/server.crt` (copy it to every client).

**b. Create the settings file:**

```sh
cp config/server.example.json config/server.json
```

**c. Edit the blocklist** in `data/blacklist.txt` (one domain per line).

**d. Register each client computer** and write down the token it prints:

```sh
python run_server.py add-client pc-12
```

**e. Start the server:**

```sh
python run_server.py run
```

Make sure the computer's firewall allows incoming connections on port **9443**.

## 2. Set up each client computer

**a.** Copy the project folder, and copy `certs/server.crt` from the server into `certs/`.

**b. Create the settings file:**

```sh
cp config/client.example.json config/client.json
```

Edit it: `server_host` = the server's IP, and `client_id` + `token` from step 1d.

**c. Start the client:**

```sh
python run_client.py
```

You should see a line like
`Connected to filter server ... (TLSv1.3, key exchange x25519, cipher TLS_AES_256_GCM_SHA384)`.

**d. Set the browser's proxy** to `127.0.0.1`, port `8080`, for both HTTP and HTTPS.
(Firefox has its own proxy settings: Settings → Network Settings → Manual proxy configuration,
and tick "Also use this proxy for HTTPS".)

## 3. Try it

* Open an allowed site, e.g. `https://www.ynet.co.il` → opens normally.
* Open `http://neverssl.com` → the block page.
* Open `https://www.facebook.com` → the browser shows an error (blocked HTTPS sites can't show our page).
* On the server: `python run_server.py logs` → a table of all checks.

Testing from the command line, without a browser:

```sh
curl -x http://127.0.0.1:8080 https://example.com -I
curl -x http://127.0.0.1:8080 http://neverssl.com
```

## Server commands

| Command | What it does |
|---|---|
| `python run_server.py run` | Load the blocklist and start the server |
| `python run_server.py import` | Load `data/blacklist.txt` again after editing it (no restart needed) |
| `python run_server.py add-client <id>` | Register a client and print its token (run again to get a new token) |
| `python run_server.py logs [count]` | Show the latest checks |

## Tests

```sh
python -m unittest discover tests
```

The full test plan, the two-computer guide and how to show the encryption in Wireshark
are in [docs/TESTING.md](docs/TESTING.md). A ready-made capture to open in Wireshark is in
[docs/wireshark](docs/wireshark).

## Project files

| Folder / file | What's inside |
|---|---|
| `run_server.py`, `run_client.py` | Start the server / the client |
| `common/` | Code shared by both: the protocol, host-name helpers, TLS settings |
| `server/` | Filter server: TLS server, policy, database, importer, access log |
| `client/` | Client app: local proxy, connection to the server, relay, block page |
| `config/` | Example settings (`*.example.json`). The real ones are not in git (they contain tokens). |
| `data/blacklist.txt` | The blocklist |
| `scripts/make_cert.sh` | Creates the server certificate |
| `tools/capture_tap.py` | Demo tool: records connection B into a file Wireshark can open |
| `tests/` | Automatic tests |
| `docs/` | Architecture and plan |
