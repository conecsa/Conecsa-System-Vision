SUMMARY = "Jetson.GPIO Python library for NVIDIA Jetson Orin Nano"
DESCRIPTION = "Access to /dev/gpiochip0/1 via Python. The inference-service \
imports this module via the bind-mount /usr/lib/python3/dist-packages/Jetson \
declared in docker-compose.yml — so the exact path must exist in the rootfs."
HOMEPAGE = "https://github.com/NVIDIA/jetson-gpio"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE.txt;md5=963ead04a49bf4a1fe8567be3d7c0b63"

SRC_URI = "git://github.com/NVIDIA/jetson-gpio.git;protocol=https;branch=master"
SRCREV = "174a681425e5fcaebf3dfdfb6dacdb0386ee31db"
PV = "2.1.9+git${SRCPV}"

S = "${WORKDIR}/git"

inherit setuptools3

RDEPENDS:${PN} = "python3-core"

# Creates the /usr/lib/python3/dist-packages/Jetson path expected by
# docker-compose.yml. Yocto installs into /usr/lib/python3.10/site-packages
# by default; the symlink preserves the Debian-style path the app expects.
do_install:append() {
    install -d ${D}${libdir}/python3/dist-packages
    ln -sf ${PYTHON_SITEPACKAGES_DIR}/Jetson ${D}${libdir}/python3/dist-packages/Jetson

    # The upstream rule uses the gpio group. On this image GID 999 already
    # belongs to the render group, which is also the GID used in docker-compose.yml.
    if [ -f ${S}/lib/python/Jetson/GPIO/99-gpio.rules ]; then
        install -d ${D}${sysconfdir}/udev/rules.d
        sed -e 's/root:gpio/root:render/g' \
            -e 's/GROUP="gpio"/GROUP="render"/g' \
            ${S}/lib/python/Jetson/GPIO/99-gpio.rules \
            > ${D}${sysconfdir}/udev/rules.d/99-gpio.rules
        chmod 0644 ${D}${sysconfdir}/udev/rules.d/99-gpio.rules
    fi
}

FILES:${PN} += " \
    ${libdir}/python3/dist-packages/Jetson \
    ${sysconfdir}/udev/rules.d/99-gpio.rules \
    "
