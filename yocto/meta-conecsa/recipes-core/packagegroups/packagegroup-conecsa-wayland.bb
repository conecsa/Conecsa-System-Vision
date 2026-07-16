SUMMARY = "Wayland + Weston for the hub-vision kiosk (Tauri)"
DESCRIPTION = "Minimal compositor on the host, running the hub-vision Tauri \
app as a kiosk on the DisplayPort (see conecsa-hub-kiosk). Containers that \
need a display can also mount the compositor socket (/run/weston/wayland-0)."
LICENSE = "MIT"

# egl-wayland and libdrm are dynamically renamed by debian-style packaging
# (libnvidia-egl-wayland1, libdrm2), which an allarch packagegroup must not
# reference — same reason packagegroup-conecsa-nvidia is machine-specific.
PACKAGE_ARCH = "${MACHINE_ARCH}"

inherit packagegroup

# Weston and libwayland come from core poky/meta-oe. meta-tegra provides a
# weston-init.bbappend that enables the NVIDIA EGL/DRM integrations.
# egl-wayland (from meta-tegra) is the backend that bridges Mesa EGL to
# NVIDIA's libwayland-egl (already included in tegra-libraries-eglcore via
# packagegroup-conecsa-nvidia).
RDEPENDS:${PN} = " \
    weston \
    weston-init \
    weston-examples \
    \
    libdrm \
    mesa \
    \
    egl-wayland \
    "

# xwayland would be added when some legacy X11 container is introduced.
# RDEPENDS:${PN} += "xwayland"
