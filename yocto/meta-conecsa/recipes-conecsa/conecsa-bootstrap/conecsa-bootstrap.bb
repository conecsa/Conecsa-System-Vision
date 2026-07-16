SUMMARY = "Conecsa boot configuration: docker daemon, udev gpio, tmpfiles SHM"
DESCRIPTION = "Installs /etc/docker/daemon.json with the nvidia runtime, the \
udev rule for /dev/gpiochip*, tmpfiles.d for /dev/shm, and enables the systemd \
services the docker-compose stack expects to find running at boot."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://daemon.json \
    file://50-conecsa-gpio.rules \
    file://conecsa-shm.conf \
    file://20-wired.network \
    file://00-conecsa-ntp.conf \
    file://zram.conf \
    file://99-conecsa-memory.conf \
    file://30-wireless.network \
    file://wpa_supplicant.conf.example \
    file://10-conecsa-sshd-hardening.conf \
    file://conecsa-hub.avahi.service \
    file://conecsa-set-hostname.sh \
    file://conecsa-hostname.service \
    file://10-conecsa-wait-online.conf \
    "

S = "${WORKDIR}"

inherit allarch systemd

# On this image GID 999 is already reserved for the systemd/udev "render"
# group. The GPIO rules use that group to preserve the group_add "999" from
# docker-compose.

do_install() {
    # docker daemon
    install -d ${D}${sysconfdir}/docker
    install -m 0644 ${WORKDIR}/daemon.json ${D}${sysconfdir}/docker/daemon.json

    # udev rule
    install -d ${D}${sysconfdir}/udev/rules.d
    install -m 0644 ${WORKDIR}/50-conecsa-gpio.rules \
        ${D}${sysconfdir}/udev/rules.d/50-conecsa-gpio.rules

    # tmpfiles.d for /dev/shm
    install -d ${D}${sysconfdir}/tmpfiles.d
    install -m 0644 ${WORKDIR}/conecsa-shm.conf \
        ${D}${sysconfdir}/tmpfiles.d/conecsa-shm.conf

    # systemd-networkd DHCP fallback for any eth*/en* interface. Without
    # this, the image boots with only docker0 + lo (systemd-networkd is
    # enabled but has no .network match → ignores the physical NIC).
    install -d ${D}${sysconfdir}/systemd/network
    install -m 0644 ${WORKDIR}/20-wired.network \
        ${D}${sysconfdir}/systemd/network/20-wired.network

    # systemd-timesyncd: pin a public NTP server since the local LAN
    # advertises an NTP server via DHCP option 42 that is unreachable
    # (8.0.160.200:123 times out). The .network file above disables use of
    # the DHCP NTP option; this conf overrides the server list.
    install -d ${D}${sysconfdir}/systemd/timesyncd.conf.d
    install -m 0644 ${WORKDIR}/00-conecsa-ntp.conf \
        ${D}${sysconfdir}/systemd/timesyncd.conf.d/00-conecsa-ntp.conf

    # Override of the zram-swap-init default (meta-openembedded zram_0.2.bb).
    # Without this file zram allocates 100% of RAM with lz4; with it the
    # device drops to 50% of RAM (algorithm stays lz4 because the L4T kernel
    # was not built with CONFIG_CRYPTO_ZSTD).
    install -d ${D}${sysconfdir}/default
    install -m 0644 ${WORKDIR}/zram.conf \
        ${D}${sysconfdir}/default/zram

    # Memory sysctl tuning, paired with the zram above and with
    # transparent_hugepage=madvise on the kernel cmdline.
    install -d ${D}${sysconfdir}/sysctl.d
    install -m 0644 ${WORKDIR}/99-conecsa-memory.conf \
        ${D}${sysconfdir}/sysctl.d/99-conecsa-memory.conf

    # WiFi: systemd-networkd DHCP for any wireless interface (Type=wlan
    # matches wlP* / wlan* regardless of predictable-name layout). The
    # credentials file is shipped as a template only — the operator copies
    # it to wpa_supplicant-<iface>.conf and enables wpa_supplicant@<iface>
    # after first boot. No SSID/PSK baked into the image (anti-leak via
    # the git repo / image artifacts).
    install -m 0644 ${WORKDIR}/30-wireless.network \
        ${D}${sysconfdir}/systemd/network/30-wireless.network
    install -d ${D}${sysconfdir}/wpa_supplicant
    install -m 0644 ${WORKDIR}/wpa_supplicant.conf.example \
        ${D}${sysconfdir}/wpa_supplicant/wpa_supplicant.conf.example

    # Don't let systemd-networkd-wait-online block boot (and thus docker and
    # the whole compose stack) on a managed-but-down NIC. The default waits for
    # ALL links and times out after 120s; --any + a short timeout caps it.
    install -d ${D}${systemd_system_unitdir}/systemd-networkd-wait-online.service.d
    install -m 0644 ${WORKDIR}/10-conecsa-wait-online.conf \
        ${D}${systemd_system_unitdir}/systemd-networkd-wait-online.service.d/10-conecsa-wait-online.conf

    # SSH hardening: key-only login, no passwords, root via key only. The
    # drop-in is parsed before the debug-tweaks lines (Include is near the
    # top of sshd_config) so it wins. Serial console stays as the
    # provisioning/recovery channel. The allowed-hosts restriction is set
    # per key (from="...") when the operator pastes authorized_keys over
    # serial — see the comments in the file.
    install -d ${D}${sysconfdir}/ssh/sshd_config.d
    install -m 0644 ${WORKDIR}/10-conecsa-sshd-hardening.conf \
        ${D}${sysconfdir}/ssh/sshd_config.d/10-conecsa-sshd-hardening.conf

    # Pre-create /root/.ssh with strict perms so the operator can drop
    # authorized_keys over serial without sshd rejecting it for loose
    # ownership/permissions. (sshd requires the dir 0700 and the file 0600,
    # both owned by root.)
    install -d -m 0700 ${D}/root/.ssh

    # mDNS: advertise _conecsa._tcp from the HOST avahi-daemon so the
    # conecsa-hub-vision app can discover this device. The api-gateway runs on a
    # docker bridge network, so its in-container advertiser only reaches the
    # bridge (172.18.x) — host avahi advertises the real LAN address instead.
    install -d ${D}${sysconfdir}/avahi/services
    install -m 0644 ${WORKDIR}/conecsa-hub.avahi.service \
        ${D}${sysconfdir}/avahi/services/conecsa-hub.service

    # Unique-hostname-on-first-boot helper + its oneshot unit. Prevents multiple
    # devices on one LAN from colliding (the hub identifies a device by hostname).
    install -d ${D}${sbindir}
    install -m 0755 ${WORKDIR}/conecsa-set-hostname.sh \
        ${D}${sbindir}/conecsa-set-hostname
    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${WORKDIR}/conecsa-hostname.service \
        ${D}${systemd_system_unitdir}/conecsa-hostname.service
}

FILES:${PN} = " \
    ${sysconfdir}/docker/daemon.json \
    ${sysconfdir}/udev/rules.d/50-conecsa-gpio.rules \
    ${sysconfdir}/tmpfiles.d/conecsa-shm.conf \
    ${sysconfdir}/systemd/network/20-wired.network \
    ${sysconfdir}/systemd/network/30-wireless.network \
    ${sysconfdir}/systemd/timesyncd.conf.d/00-conecsa-ntp.conf \
    ${sysconfdir}/default/zram \
    ${sysconfdir}/sysctl.d/99-conecsa-memory.conf \
    ${sysconfdir}/wpa_supplicant/wpa_supplicant.conf.example \
    ${systemd_system_unitdir}/systemd-networkd-wait-online.service.d/10-conecsa-wait-online.conf \
    ${sysconfdir}/ssh/sshd_config.d/10-conecsa-sshd-hardening.conf \
    ${sysconfdir}/avahi/services/conecsa-hub.service \
    ${sbindir}/conecsa-set-hostname \
    ${systemd_system_unitdir}/conecsa-hostname.service \
    /root/.ssh \
    "

# Services that must be active at boot. nvargus-daemon comes from
# nvidia-l4t-camera (ARGUS camera daemon). nv-tee-supplicant comes from the
# OP-TEE BSP. weston IS enabled at boot (weston-init auto-enables its units;
# the image sets SYSTEMD_DEFAULT_TARGET=graphical.target) and runs the
# hub-vision kiosk via [autolaunch] — see conecsa-hub-kiosk and the
# weston-init bbappend in this layer.
SYSTEMD_SERVICE:${PN} = " "
SYSTEMD_AUTO_ENABLE:${PN} = "disable"

# Enable docker.service at boot. The docker-moby recipe only registers
# docker.socket (on-demand activation), which does NOT start dockerd at
# boot — so containers with `restart: unless-stopped` would not come back
# after reboot. We enable docker.service explicitly here (we cannot use
# SYSTEMD_SERVICE because the unit belongs to the docker-moby package and
# the QA systemd_check_services check would reject it). docker.service has
# [Install] WantedBy=multi-user.target, so offline enable works.
pkg_postinst:${PN}() {
    if type systemctl >/dev/null 2>/dev/null; then
        OPTS=""
        [ -n "$D" ] && OPTS="--root=$D"
        systemctl $OPTS enable docker.service
        # Advertise _conecsa._tcp on the LAN for conecsa-hub-vision discovery.
        # avahi-daemon.service belongs to the avahi-daemon package (oe-core), so
        # we enable it here rather than via SYSTEMD_SERVICE (QA would reject a
        # foreign unit). It has [Install] WantedBy=multi-user.target.
        systemctl $OPTS enable avahi-daemon.service
        # Assign a unique hostname on first boot (before networking/avahi).
        systemctl $OPTS enable conecsa-hostname.service
    fi
}

# RDEPENDS enforces the order: docker/containerd/nvidia-container-toolkit
# are installed before /etc/docker/daemon.json becomes useful. The recipe
# that provides /usr/bin/nvidia-container-runtime is nvidia-container-toolkit
# in meta-tegra (there is no separate nvidia-container-runtime recipe).
# avahi-daemon (oe-core) provides the host mDNS responder + avahi-daemon.service
# enabled above; it publishes /etc/avahi/services/conecsa-hub.service on the LAN.
RDEPENDS:${PN} = " \
    docker-moby \
    containerd-opencontainers \
    nvidia-container-toolkit \
    wpa-supplicant \
    avahi-daemon \
    "
