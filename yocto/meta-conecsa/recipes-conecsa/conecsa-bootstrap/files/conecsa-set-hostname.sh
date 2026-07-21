#!/bin/sh
# Assign a unique hostname so multiple devices on the same LAN don't collide in
# mDNS / the conecsa-hub-vision registry (which identifies a device by its
# hostname), and publish that hostname as the device identity in the host mDNS
# advertisement. Assigning the hostname is idempotent: it only acts while the
# hostname is still the image default, so one set by the operator is preserved.
# The identity is (re)published on every run.
set -eu

DEFAULT="conecsa-system-vision"
AVAHI_SERVICE=/etc/avahi/services/conecsa-hub.service

# State the device identity in the host mDNS advertisement as TXT records.
#
# The hostname IS the identity: enrollment puts it in the certificate SAN, and the
# hub keys its paired-set by it. avahi renames a *colliding* service instance
# (`conecsa-x` becomes `conecsa-x-2`) and does not substitute %h inside
# <txt-record> — so an advertisement carrying no explicit id leaves the hub to
# infer the identity from the (possibly renamed) instance name, and a renamed
# device then matches neither its own certificate nor the hub's paired-set. TXT
# records survive the rename, so spell the identity out instead of implying it.
publish_identity() {
    name="$1"
    [ -n "$name" ] || return 0
    [ -r "$AVAHI_SERVICE" ] || return 0

    tmp="$AVAHI_SERVICE.tmp"
    # Drop the identity records of an earlier run (the hostname may have changed
    # since) and re-emit them right after the service type.
    awk -v id="$name" '
        /<txt-record>(device_id|name)=/ { next }
        { print }
        /<type>_conecsa\._tcp<\/type>/ {
            printf "    <txt-record>device_id=%s</txt-record>\n", id
            printf "    <txt-record>name=%s</txt-record>\n", id
        }
    ' "$AVAHI_SERVICE" > "$tmp" || { rm -f "$tmp"; return 0; }
    mv "$tmp" "$AVAHI_SERVICE"

    # This unit is ordered before avahi-daemon at boot.  Do not synchronously
    # reload a service whose pending start job is waiting for this oneshot to
    # finish: that creates an ordering deadlock and prevents networkd/DHCP from
    # starting.  A reload is only needed when this script is rerun while Avahi
    # is already active; --no-block also keeps the helper out of Avahi's job.
    if systemctl is-active --quiet avahi-daemon 2>/dev/null; then
        systemctl reload --no-block avahi-daemon 2>/dev/null || true
    fi
}

CUR="$(hostname 2>/dev/null || echo "")"

case "$CUR" in
    "$DEFAULT"|localhost|localhost.localdomain|"") ;;
    *) publish_identity "$CUR"; exit 0 ;;  # already customized — leave it alone
esac

suffix=""
# 1) Tegra board serial — stable and unique per board.
if [ -r /proc/device-tree/serial-number ]; then
    suffix="$(tr -d '\0' < /proc/device-tree/serial-number 2>/dev/null || true)"
fi
# 2) First non-loopback MAC address.
if [ -z "$suffix" ]; then
    for f in /sys/class/net/*/address; do
        iface="$(basename "$(dirname "$f")")"
        [ "$iface" = "lo" ] && continue
        suffix="$(cat "$f" 2>/dev/null | tr -d ':' || true)"
        [ -n "$suffix" ] && break
    done
fi
# 3) systemd machine-id.
if [ -z "$suffix" ] && [ -r /etc/machine-id ]; then
    suffix="$(cat /etc/machine-id 2>/dev/null || true)"
fi

# Sanitize to a valid DNS label and keep the last 6 chars for brevity.
suffix="$(printf '%s' "$suffix" | tr 'A-Z' 'a-z' | tr -cd 'a-z0-9')"
suffix="$(printf '%s' "$suffix" | tail -c 6)"
if [ -z "$suffix" ]; then
    publish_identity "$CUR"
    exit 0
fi

NEW="conecsa-${suffix}"
if [ "$NEW" != "$CUR" ]; then
    printf '%s\n' "$NEW" > /etc/hostname
    hostname "$NEW" 2>/dev/null || true
    if command -v hostnamectl >/dev/null 2>&1; then
        hostnamectl set-hostname "$NEW" 2>/dev/null || true
    fi
fi

publish_identity "$NEW"
