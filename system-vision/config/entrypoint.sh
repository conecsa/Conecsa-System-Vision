#!/bin/sh
# nginx entrypoint that flips between the enrollment and enforcing TLS blocks
# based on whether the device has been paired (a hub-signed cert + the hub CA are
# present in the shared certs volume), and reloads nginx when that state changes.
set -e

CERTDIR=/etc/conecsa/certs
TLSCONF=/etc/nginx/conf.d/tls.conf
mkdir -p "$CERTDIR"

enrolled() {
    [ -f "$CERTDIR/device.crt" ] && [ -f "$CERTDIR/ca.crt" ]
}

ensure_snakeoil() {
    # Temporary self-signed cert for the enrollment block (TOFU during pairing).
    if [ ! -f "$CERTDIR/snakeoil.crt" ] || [ ! -f "$CERTDIR/snakeoil.key" ]; then
        openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
            -keyout "$CERTDIR/snakeoil.key" -out "$CERTDIR/snakeoil.crt" \
            -days 3650 -nodes -subj "/CN=conecsa-enroll" >/dev/null 2>&1
    fi
}

select_conf() {
    if enrolled; then
        cp /etc/nginx/conecsa/enforcing.conf "$TLSCONF"
        echo "nginx: device enrolled — enforcing mTLS on :443"
    else
        ensure_snakeoil
        cp /etc/nginx/conecsa/enroll.conf "$TLSCONF"
        echo "nginx: device not enrolled — serving /enroll on :443"
    fi
}

state() { enrolled && echo on || echo off; }

select_conf
nginx -g 'daemon off;' &
NGINX=$!

# Poll for an enrollment-state change (the api-gateway writes the certs into the
# shared volume during pairing) and reload nginx into the right block.
last=$(state)
while kill -0 "$NGINX" 2>/dev/null; do
    sleep 5
    cur=$(state)
    if [ "$cur" != "$last" ]; then
        echo "nginx: enrollment state changed ($last -> $cur); reloading"
        select_conf
        nginx -s reload || true
        last=$cur
    fi
done
