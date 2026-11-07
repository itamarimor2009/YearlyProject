#!/bin/sh
# make_cert.sh - Creates the filter server's TLS certificate and private key.
#
# Usage (run on the SERVER machine, from the project folder):
#     sh scripts/make_cert.sh <server IP address or host name>
# Example:
#     sh scripts/make_cert.sh 192.168.1.50
#
# Creates:
#     certs/server.key  - the private key. Stays on the server. NEVER share it.
#     certs/server.crt  - the certificate. Copy it to every client computer (into certs/).
#
# Note: the RSA key here is only used to SIGN the certificate (to prove who the server is).
# The encryption key of every connection is agreed with Diffie-Hellman (TLS 1.3).

set -e

if [ -z "$1" ]; then
    echo "Usage: sh scripts/make_cert.sh <server IP address or host name>"
    exit 1
fi

NAME="$1"

# The certificate must contain the address the clients use to reach the server,
# otherwise the clients will reject it. "IP:" for addresses, "DNS:" for names.
case "$NAME" in
    *[!0-9.]*) SAN="DNS:$NAME" ;;
    *)         SAN="IP:$NAME" ;;
esac

mkdir -p certs
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
    -keyout certs/server.key -out certs/server.crt \
    -subj "/CN=$NAME" \
    -addext "subjectAltName=$SAN,DNS:localhost,IP:127.0.0.1"
chmod 600 certs/server.key

echo "Done: certs/server.crt and certs/server.key (valid for $NAME, localhost and 127.0.0.1)"
