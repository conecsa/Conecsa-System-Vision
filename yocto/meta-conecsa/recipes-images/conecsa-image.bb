SUMMARY = "Conecsa Object Detection minimal image for NVIDIA Jetson Orin Nano"
DESCRIPTION = "Minimal Yocto image for hosting the Conecsa Object Detection \
app in Docker containers. Bundles only L4T drivers, the CUDA/TRT/cuDNN runtime, \
Docker + nvidia-container-runtime, V4L2 and GPIO — no host GUI."
LICENSE = "MIT"

inherit core-image

# SSH for administration; package-management for post-install apt/opkg.
# debug-tweaks enables root SSH login with a password (matches the JetPack
# default that the Conecsa app expects — `ssh root@<jetson-ip>`). In
# production, swap for `allow-root-login` and create a dedicated non-root user.
IMAGE_FEATURES += "ssh-server-openssh package-management debug-tweaks"

IMAGE_INSTALL = " \
    packagegroup-core-boot \
    packagegroup-conecsa-nvidia \
    packagegroup-conecsa-runtime \
    packagegroup-conecsa-camera \
    packagegroup-conecsa-python-gpio \
    packagegroup-conecsa-wayland \
    conecsa-bootstrap \
    kernel-modules \
    "

# The hub kiosk recipe exists only in the private monorepo (the public mirror
# exported by scripts/export-mirror.sh ships this layer without it), so it is
# installed only when its recipe directory is present in the layer.
IMAGE_INSTALL += "${@'conecsa-hub-kiosk' if os.path.isdir(os.path.join(os.path.dirname(d.getVar('FILE')), '../recipes-conecsa/conecsa-hub-kiosk')) else ''}"

# weston.service is WantedBy=graphical.target, but rootfs-postcommands
# defaults this image to multi-user.target (no x11-base/weston in
# IMAGE_FEATURES). graphical.target pulls multi-user.target in, so the
# Docker stack is unaffected.
SYSTEMD_DEFAULT_TARGET = "graphical.target"

# tegraflash produces the directory with doflash.sh + l4t_initrd_flash
# assets, ready to write to the Orin Nano NVMe in recovery mode.
IMAGE_FSTYPES = "tegraflash"

# Room for the Conecsa container images in /var/lib/docker
# (conecsa-os-base:base ~6 GB; others ~2 GB each).
IMAGE_ROOTFS_EXTRA_SPACE = "30000000"

# Root SSH enabled by default (the app is deployed via ssh root@jetson).
# Tighten before production: create a non-root user.
EXTRA_USERS_PARAMS = "usermod -P conecsa root;"
