# Site Filter Proxy — Testing

How the project is tested: automatic tests, a manual test on one computer, a test with
two computers, and showing the encryption in Wireshark.

---

## 1. Automatic tests

```sh
python -m unittest discover tests
```

| File | What it tests |
|---|---|
| `tests/test_domains.py` | Cleaning site names, parent domains (`a.b.ynet.com → b.ynet.com → ynet.com`) |
| `tests/test_protocol.py` | Sending/receiving JSON lines, too-long and broken messages |
| `tests/test_policy.py` | Blocklist file + database + decisions, subdomains, re-import, access log |
| `tests/test_proxy_parsing.py` | Reading the browser's `CONNECT` and `GET` requests |
| `tests/test_end_to_end.py` | The whole system on one computer: real TLS server, client, proxy and a small test website (no internet needed) |

Result (2026-11-07): **31 tests, all passed.**

---

## 2. Manual test on one computer

Server and client on the same computer (`server_host` = `127.0.0.1`).

| # | Test | Expected | Result |
|---|---|---|---|
| 1 | `https://example.com` | opens (200) | ✅ |
| 2 | `https://www.ynet.co.il` | opens | ✅ |
| 3 | `https://www.facebook.com` | refused with 403 | ✅ |
| 4 | `http://example.com` | opens (200) | ✅ |
| 5 | `http://neverssl.com` | block page (403) | ✅ |
| 6 | `https://example.com:8443` | refused, port not allowed | ✅ |
| 7 | `python run_server.py logs` | every check listed with time, client, IP, result, rule | ✅ |
| 8 | Stop the server, open a site | 503 "Filter server unavailable" | ✅ |
| 9 | Start the server again | sites open again, client not restarted | ✅ |
| 10 | Client with a wrong token | refused, warning in the server log | ✅ |
| 11 | Client that doesn't have `server.crt` | TLS fails ("unknown CA") | ✅ |
| 12 | Connection details printed | `TLSv1.3, key exchange x25519` | ✅ |

---

## 3. Test with two computers

**Server computer** (example IP `192.168.1.50`; find yours with `ipconfig` on Windows,
`ipconfig getifaddr en0` on Mac):

1. `sh scripts/make_cert.sh 192.168.1.50`
2. `cp config/server.example.json config/server.json`
3. `python run_server.py add-client pc-1` → copy the token
4. Allow incoming TCP port **9443** in the firewall.
5. `python run_server.py run`

**Client computer:**

1. Copy the project and `certs/server.crt` (not the key!) from the server.
2. `cp config/client.example.json config/client.json` and set `server_host` = `192.168.1.50`, `client_id`, `token`.
3. `python run_client.py` → must print `Connected to filter server 192.168.1.50:9443 (TLSv1.3, key exchange x25519, ...)`.
4. Set the browser's proxy to `127.0.0.1:8080` and repeat the tests from section 2.
5. On the server, `python run_server.py logs` must show the **client computer's IP**.

Common problems:

| Problem | Reason |
|---|---|
| `Connection refused` / timeout | Server not running, wrong IP, or firewall blocks 9443 |
| `certificate verify failed: IP address mismatch` | Certificate made for another IP → run `make_cert.sh` again with the right IP, copy `server.crt` again |
| `certificate verify failed: unable to get local issuer` | The client has an old or wrong `server.crt` |
| `The server refused the login` | Wrong `client_id` / `token` in `client.json` |

---

## 4. Showing the encryption in Wireshark

### Option A — capture live with Wireshark

1. Install Wireshark (wireshark.org).
2. Capture on the network card (two computers) or on **Loopback** (one computer).
3. Filter: `tcp.port == 9443`
4. Right-click a packet → **Decode As…** → TCP port 9443 → **TLS** (9443 isn't a standard TLS port).

### Option B — record with the tap tool (no admin rights needed)

```sh
python tools/capture_tap.py 9444 127.0.0.1 9443 capture.pcap
```

Set `"server_port": 9444` in `config/client.json`, start the client, browse a little,
stop the tap with Ctrl+C, and open `capture.pcap` in Wireshark (then Decode As… TLS as above).

### What to show

1. **Client Hello** → Extension `key_share` → Group **x25519** + the client's public key.
2. **Server Hello** → Extension `key_share` → Group **x25519** + the server's public key.
   These two public keys are the Diffie-Hellman exchange. Each side mixes its secret with the
   other side's public key and both get the same secret — which never travels on the network.
3. Everything after that is **Application Data**: encrypted, unreadable. Even the server's
   certificate is encrypted in TLS 1.3.
4. **Optional — decrypt our own traffic:** add `"tls_keylog_file": "keys.log"` to
   `config/client.json`, restart the client, then in Wireshark: *Preferences → Protocols → TLS →
   (Pre)-Master-Secret log filename* → `keys.log`. Now Wireshark shows our JSON messages
   (`hello`, `check`, `result`). This proves that **without the keys nobody can read them**.
   Remove the setting after the demo.
