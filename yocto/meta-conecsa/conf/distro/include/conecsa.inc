DISTRO = "conecsa"
DISTRO_NAME = "Conecsa Object Detection minimal distro"
DISTRO_VERSION_BASE = "1.0"
DISTRO_VERSION = "${DISTRO_VERSION_BASE}+snapshot-${METADATA_REVISION}"
DISTRO_CODENAME = "scarthgap"
SDK_VENDOR = "-conecsasdk"
SDK_VERSION = "${@d.getVar('DISTRO_VERSION').replace('snapshot-${METADATA_REVISION}', 'snapshot')}"
SDK_VERSION[vardepvalue] = "${SDK_VERSION}"

MAINTAINER = "Cristiano Leite <cristianosleite@hotmail.com>"

TARGET_VENDOR = "-conecsa"

# Bump whenever the layer/config layout changes incompatibly.
LOCALCONF_VERSION = "1"

# Minimal features: systemd init, virtualization (docker), wayland (for future
# desktop containers), opengl (EGL nvidia-l4t-3d-core). Removed: x11, ptest,
# multiarch, vulkan (the app is TensorRT-only and uses CUDA only), pam.
DISTRO_FEATURES_CONECSA = "largefile opengl wayland systemd virtualization usrmerge"

DISTRO_FEATURES ?= "${DISTRO_FEATURES_DEFAULT} ${DISTRO_FEATURES_CONECSA}"

# Kernel target. The Jetson Orin Nano today runs 5.15.x-tegra but meta-tegra
# scarthgap ships linux-tegra as the preferred recipe. We keep 6.6 as a
# fallback in case meta-tegra does not pin the NV version.
PREFERRED_VERSION_linux-yocto ?= "6.6%"
PREFERRED_VERSION_linux-yocto-rt ?= "6.6%"

SDK_NAME = "${DISTRO}-${TCLIBC}-${SDKMACHINE}-${IMAGE_BASENAME}-${TUNE_PKGARCH}-${MACHINE}"
SDKPATHINSTALL = "/opt/${DISTRO}/${SDK_VERSION}"

TCLIBCAPPEND = ""

# rpm: tegrademo default; kept for compatibility with NVIDIA recipes.
PACKAGE_CLASSES ?= "package_rpm"

SANITY_TESTED_DISTROS ?= " \
            ubuntu-22.04 \n \
            ubuntu-24.04 \n \
            debian-12 \n \
            debian-13 \n \
            "

# The NVIDIA stack assumes systemd. Do not switch to sysvinit.
INIT_MANAGER = "systemd"

require conf/distro/include/no-static-libs.inc
require conf/distro/include/yocto-uninative.inc
require conf/distro/include/security_flags.inc
INHERIT += "uninative"

# Allow commercial packages (e.g. faad2/x264 used by NVIDIA gstreamer).
LICENSE_FLAGS_ACCEPTED += "commercial_faad2 commercial_x264"

# avahi-daemon is in the image PACKAGE_EXCLUDE (build/conf/local.conf) as part of
# the "no extra daemons" minimal policy, but conecsa-bootstrap now requires it to
# advertise _conecsa._tcp on the LAN for conecsa-hub-vision discovery. Drop it
# from the exclude list (`:remove` is applied last, so it overrides the `+=` in
# local.conf) rather than editing local.conf.
PACKAGE_EXCLUDE:remove = "avahi-daemon"

# Redundant (A/B) flash layout is the meta-tegra default; kept for compatibility.
USE_REDUNDANT_FLASH_LAYOUT_DEFAULT ?= "1"
