# The poky seatd recipe ships no systemd unit (only a sysvinit script when the
# init manager is not systemd). The kiosk needs the seatd daemon running as
# root to mediate VT/DRM/input access for the unprivileged weston user — the
# libseat builtin backend cannot open /dev/tty0 as non-root (validated on the
# device). Socket group `video`, which the weston user is already in.
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

inherit systemd

SRC_URI += "file://seatd.service"

do_install:append() {
    install -Dm0644 ${WORKDIR}/seatd.service \
        ${D}${systemd_system_unitdir}/seatd.service
}

SYSTEMD_SERVICE:${PN} = "seatd.service"

FILES:${PN} += "${systemd_system_unitdir}/seatd.service"
