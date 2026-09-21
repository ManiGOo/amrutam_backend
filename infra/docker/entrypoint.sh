#!/usr/bin/env bash
set -euo pipefail

# Generate self-signed TLS for nginx (dev) + JWT RS256 keypair if missing.
# /run/secrets is a shared named volume so all api replicas use ONE keypair.
# Operate: start 1 api replica first (generates), then --scale api=3.
mkdir -p tls /run/secrets

if [ ! -f tls/tls.crt ] || [ ! -f tls/tls.key ]; then
  openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout tls/tls.key -out tls/tls.crt \
    -subj "/CN=localhost" >/dev/null 2>&1
  echo "generated self-signed TLS cert"
fi

if [ ! -f /run/secrets/jwt_private.pem ]; then
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 \
    -out /run/secrets/jwt_private.pem 2>/dev/null
  openssl rsa -pubout -in /run/secrets/jwt_private.pem \
    -out /run/secrets/jwt_public.pem 2>/dev/null
  echo "generated JWT RS256 keypair"
fi

exec "$@"
