SUMMARY = "V4L2 support for webcam-server (MJPEG/YUYV/Bayer capture)"
LICENSE = "MIT"

PACKAGE_ARCH = "${MACHINE_ARCH}"

inherit packagegroup

# /dev/video0 is provided by the L4T kernel (CSI/USB).
# libv4l + v4l-utils let the webcam-server container (Rust + v4l crate) talk
# to the device. udev is required to create the nodes in /dev.

RDEPENDS:${PN} = " \
    v4l-utils \
    libv4l \
    libudev \
    udev \
    systemd-udev-rules \
    "
