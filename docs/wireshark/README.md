# Demo capture of connection B

A real recording of one client session (made with `tools/capture_tap.py`, 2026-11-07):
the client logged in and checked four sites (www.ynet.co.il, www.facebook.com, neverssl.com, example.com).

| File | What it is |
|---|---|
| `demo_capture.pcap` | The recorded packets. Open it in Wireshark. |
| `demo_keys.log` | The TLS session keys of **this demo session only** (saved with the client's demo setting `tls_keylog_file`). They belong to a throw-away test certificate and can't decrypt anything else. |

In Wireshark:

1. Open `demo_capture.pcap`.
2. Right-click a packet → **Decode As…** → TCP port **19443** → **TLS**.
3. Packet 4 (Client Hello) and packet 5 (Server Hello) → *Extension: key_share* → *Group: x25519* — the Diffie-Hellman public keys.
4. Packets 6–17 show only **Application Data** (encrypted).
5. To decrypt: *Preferences → Protocols → TLS → (Pre)-Master-Secret log filename* → `demo_keys.log`.
   Now packets 8–17 show the JSON messages `hello`, `hello_ok`, `check` and `result`.
