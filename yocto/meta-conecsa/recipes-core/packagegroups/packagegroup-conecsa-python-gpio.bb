SUMMARY = "Python 3 + Jetson.GPIO for bind-mount into the inference-service"
DESCRIPTION = "The inference-service imports Jetson.GPIO. The module is \
mounted read-only from the host at /usr/lib/python3/dist-packages/Jetson — \
so it must exist in the Jetson rootfs."
LICENSE = "MIT"

inherit packagegroup

RDEPENDS:${PN} = " \
    python3 \
    python3-core \
    python3-jetson-gpio \
    "
