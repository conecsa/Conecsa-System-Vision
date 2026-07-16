SUMMARY = "Docker engine + nvidia-container-runtime for hosting the Conecsa app"
LICENSE = "MIT"

inherit packagegroup

# docker-moby comes from meta-virtualization. nvidia-container-toolkit and
# libnvidia-container come from meta-tegra/external/virtualization-layer/.
# tegra-container-passthrough configures pass-through of Tegra libraries
# into containers (NVIDIA_VISIBLE_DEVICES, etc.).
RDEPENDS:${PN} = " \
    docker-moby \
    docker-compose \
    containerd-opencontainers \
    runc-opencontainers \
    \
    nvidia-container-toolkit \
    libnvidia-container \
    \
    tegra-container-passthrough \
    \
    iptables \
    cgroup-lite \
    \
    zram \
    "
