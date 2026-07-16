"""Performance clock pinning for the Jetson host.

Without `jetson_clocks`, the Tegra dynamic governors (GPU `nvhost_podgov`, CPU
`schedutil`) keep clocks low for the bursty TensorRT inference workload — the GPU
sits at its minimum (306 of 918 MHz), roughly doubling per-frame inference time.
The privileged `os` hardware agent owns host hardware, so it pins the performance
clocks at startup (the container can write the host `/sys` clock nodes). This is
the core of what `jetson_clocks` does (GPU + CPU); it persists for the life of the
agent and re-applies on every restart.

Opt out with ``PIN_PERFORMANCE_CLOCKS=0``.
"""
import glob
import logging
import os

logger = logging.getLogger(__name__)

_GPU_DEVFREQ = "/sys/class/devfreq/17000000.gpu"


def _write(path: str, value: str) -> bool:
    """Write *value* to a sysfs *path*; log and return False on failure."""
    try:
        with open(path, "w") as f:
            f.write(value)
        return True
    except OSError as exc:
        logger.warning("clocks: could not write %s = %s (%s)", path, value, exc)
        return False


def pin_performance_clocks() -> None:
    """Pin the GPU to its max frequency and the CPU cores to `performance`."""
    if os.environ.get("PIN_PERFORMANCE_CLOCKS", "1") != "1":
        logger.info("clocks: performance pinning disabled (PIN_PERFORMANCE_CLOCKS=0)")
        return

    # GPU: min_freq = max_freq pins it at the top regardless of the governor
    # (the governor cannot scale below min). This is what jetson_clocks does.
    try:
        with open(f"{_GPU_DEVFREQ}/max_freq") as f:
            gpu_max = f.read().strip()
        if _write(f"{_GPU_DEVFREQ}/min_freq", gpu_max):
            logger.info("clocks: GPU pinned to %s Hz", gpu_max)
    except OSError as exc:
        logger.warning("clocks: GPU devfreq unavailable (%s)", exc)

    # CPU: `performance` governor on every online core.
    cores = sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor"))
    pinned = sum(_write(gov, "performance") for gov in cores)
    if pinned:
        logger.info("clocks: %d/%d CPU cores set to performance governor", pinned, len(cores))
