SUMMARY = "NVIDIA L4T BSP + CUDA + TensorRT + cuDNN + cuDLA for Jetson Orin Nano"
LICENSE = "MIT"

PACKAGE_ARCH = "${MACHINE_ARCH}"

inherit packagegroup

# Maps the nvidia-l4t-* packages from JetPack 6.2.2 (Jetson dpkg) to the
# equivalent meta-tegra scarthgap recipes.
# Validated via inventory in meta-tegra/recipes-bsp/tegra-binaries/ and
# meta-tegra/recipes-devtools/cuda/.

RDEPENDS:${PN} = " \
    \
    nv-tegra-release \
    tegra-firmware \
    tegra-configs-udev \
    tegra-configs-nvstartup \
    tegra-configs-container-csv \
    tegra-tools \
    \
    tegra-libraries-core \
    tegra-libraries-cuda \
    tegra-libraries-camera \
    tegra-libraries-multimedia \
    tegra-libraries-multimedia-utils \
    tegra-libraries-multimedia-v4l \
    tegra-libraries-gbm-backend \
    tegra-libraries-eglcore \
    tegra-libraries-glescore \
    tegra-libraries-glxcore \
    tegra-libraries-nvml \
    tegra-libraries-nvsci \
    tegra-libraries-pva \
    tegra-libraries-dla-compiler \
    \
    tegra-argus-daemon \
    tegra-mmapi \
    \
    tegra-nvstartup \
    tegra-nvpmodel \
    tegra-nvphs \
    tegra-nvpower \
    tegra-nvfancontrol \
    tegra-nvs-service \
    tegra-nvsciipc \
    \
    cuda-cudart \
    cuda-driver \
    cuda-nvtx \
    cuda-cupti \
    cuda-nvrtc \
    cuda-libraries \
    cuda-command-line-tools \
    \
    libcublas \
    libcufft \
    libcurand \
    libcusolver \
    libcusparse \
    libnpp \
    libnvjpeg \
    libnvjitlink \
    libcudla \
    \
    cudnn \
    \
    tensorrt-core \
    tensorrt-plugins-prebuilt \
    tensorrt-trtexec-prebuilt \
    \
    nvidia-drm-loadconf \
    \
    nv-kernel-module-r8168 \
    nv-kernel-module-r8126 \
    \
    nv-kernel-module-rtl8822ce \
    tegra-firmware-rtl8822 \
    linux-firmware-rtl8822 \
    wireless-regdb-static \
    "
