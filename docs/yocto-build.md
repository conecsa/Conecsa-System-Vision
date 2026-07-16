# Yocto build of the minimal Jetson Orin Nano image

Custom image to host the Conecsa Object Detection application in Docker
containers, replacing the stock NVIDIA JetPack 6.2.2 (Ubuntu 22.04, ~2245
packages) with a lean Yocto rootfs based on `tegra-demo-distro` branch
`scarthgap` (Yocto 5.0, L4T R36.5.0 = JetPack 6.2.2 — same CUDA 12.6 /
TensorRT 10.3 / cuDNN 9 versions that `docker-compose.yml` expects).

## Architecture

```
yocto/
├── kas-config.yml                # entry point for kas-container build
└── meta-conecsa/                 # custom Yocto layer
    ├── conf/layer.conf
    ├── recipes-images/
    │   └── conecsa-image.bb      # final image, IMAGE_FSTYPES=tegraflash,
    │                             #   SYSTEMD_DEFAULT_TARGET=graphical.target
    ├── recipes-core/packagegroups/
    │   ├── packagegroup-conecsa-nvidia.bb       # L4T BSP + CUDA + TRT + cuDNN + cuDLA
    │   ├── packagegroup-conecsa-runtime.bb      # docker-moby + nvidia-container-runtime
    │   ├── packagegroup-conecsa-camera.bb       # V4L2 + libv4l + v4l-utils
    │   ├── packagegroup-conecsa-wayland.bb      # Weston + Mesa + egl-wayland (kiosk)
    │   └── packagegroup-conecsa-python-gpio.bb  # Python 3 + Jetson.GPIO
    ├── recipes-conecsa/
    │   ├── jetson-gpio/python3-jetson-gpio_2.1.9.bb
    │   ├── conecsa-bootstrap/conecsa-bootstrap.bb
    │   └── conecsa-hub-kiosk/conecsa-hub-kiosk.bb  # hub-vision kiosk glue
    ├── recipes-poky-overrides/
    │   ├── weston-init/          # kiosk weston.ini + no-PAM systemd drop-in
    │   ├── weston/               # REQUIRED_DISTRO_FEATURES pam removal
    │   └── seatd/                # seatd.service (poky ships none for systemd)
    ├── recipes-oe-overrides/
    │   └── webkitgtk3/           # DEPENDS += virtual/libgbm (tegra)
    └── recipes-distro/conecsa-distro.conf
```

## Build host prerequisites

- Linux x86_64 (Ubuntu 22.04+ recommended; ARM works for building but not for flashing)
- Docker engine
- ≥ 150 GB free disk (downloads + sstate + tmp)
- ≥ 16 GB RAM (32 GB recommended for decent parallelism)
- USB-C → USB-A/C cable to put the Jetson into recovery mode at flash time

Install kas-container:

Note: Consider creating a virtual environment first.

```bash
python -m pip install kas
docker pull ghcr.io/siemens/kas/kas:4.7
```

## Build

```bash
# IMPORTANT: pin kas to 4.7 (Debian 12 / gcc 12). Version 5.x uses
# Debian 13 / gcc 14, which is incompatible with Yocto scarthgap
# (validated against Ubuntu 22.04 / Debian 12 / gcc 13). Without this,
# gcc-cross do_compile fails with "undefined reference to `main`" inside
# native fixincludes.
export KAS_IMAGE_VERSION=4.7

# Build in the background, redirect everything (stdout + stderr) to a
# log file so the build survives a closed terminal and can be tailed
# from any other shell.
mkdir -p /tmp/kas-container
cd yocto && \
    kas-container build kas-config.yml > /tmp/kas-container/build.log 2>&1 &

# Follow progress live from another shell (or the same one):
tail -f /tmp/kas-container/build.log

# Useful greps while tailing:
#   grep -E 'ERROR|FAILED'  /tmp/kas-container/build.log
#   grep -E 'Currently.*tasks running' /tmp/kas-container/build.log | tail -1
```

First build: **2–4h** (meta-tegra downloads are ~25 GB; CUDA build is expensive).
Incremental builds: **30–60 min** (depending on your hardware settings).
The cache lives in `yocto/build/cache`.

> Drop the trailing `&` if you want the command to stay in the foreground.
> The redirect + `tail -f` workflow above is what you want for
> long-running builds where the terminal might get closed.

Final artifact (a self-contained tarball that bundles the flasher):
```
yocto/build/tmp/deploy/images/jetson-orin-nano-devkit-nvme/
└── conecsa-image-jetson-orin-nano-devkit-nvme.rootfs.tegraflash.tar.gz
```

The `.rootfs.tegraflash.tar.gz` unpacks to ~596 files, including the
`initrd-flash` script (the flash entry point, see the Flash section), the
`initrd-flash.img` image (cboot initramfs booted via RCM), `doflash.sh`,
`.env.initrd-flash` (board variables) and every signed bootloader binary.
A standalone `doflash.sh`/`tegra-flash-helper.sh` in the deploy directory
**no longer exists** — everything comes inside the tarball.

The `jetson-orin-nano-devkit-nvme` variant (vs. `jetson-orin-nano-devkit`,
which targets microSD) makes meta-tegra emit `external-flash.xml.in` plus
the `flash_l4t_t234_nvme.xml` layout, with `EXTERNAL_ROOTFS_DRIVE=1` and
`ROOTFS_DEVICE=nvme0n1`. Without this the rootfs ends up on the microSD slot.

## NVMe partition layout (critical)

`conecsa-image` reserves `IMAGE_ROOTFS_EXTRA_SPACE = "30000000"` (30 GiB)
for Docker images in `/var/lib/docker`, which makes the final ext4 ~36 GiB
base — **larger than the default APP partition**. The orin-nano default is
`ROOTFSPART_SIZE_DEFAULT = 30064771072` (~28 GiB) and, with A/B redundancy
(enabled by `meta-conecsa/conf/distro/include/conecsa.inc`), that is split
in half → ~14 GiB per slot. The flash aborts with
`failed to write conecsa-image.ext4` because the image does not fit.

Fix applied in `kas-config.yml` (`local_conf_header.conecsa`), targeting the
**128 GB** NVMe of this hardware — single ~115 GB rootfs, no A/B:

```text
USE_REDUNDANT_FLASH_LAYOUT = "0"
ROOTFSPART_SIZE_DEFAULT    = "115003392000"   # 28_077_000 * 4096 (~115 GB, 4 KiB aligned)
TEGRA_EXTERNAL_DEVICE_SECTORS = "240000000"   # 240M * 512 = 122.88 GB (~96% of the SSD)
```

- `USE_REDUNDANT_FLASH_LAYOUT="0"` drops the
  `L4TConfiguration-RootfsRedundancyLevelABEnable.dtbo` overlay, switches the
  partition template to the non-redundant variant, and gives the full 115 GB
  to `APP` (no `APP_b`). The **kernel/DTB/recovery/ESP** partitions remain
  A/B-duplicated — that is hard-wired in the L4T BCT and is not affected by
  this flag.
- `ROOTFSPART_SIZE_DEFAULT` must be ≥ the ext4 size and a multiple of 4096.
- `TEGRA_EXTERNAL_DEVICE_SECTORS` must fit in the physical SSD (leave margin
  for the NVMe controller's overprovisioning).

For a different SSD size, scale both values proportionally. To keep A/B
(automatic OTA rollback), use `ROOTFSPART_SIZE_DEFAULT` ~2× the ext4 size
(each slot takes half).

## Post-build validations (before flashing)

> **IMPORTANT — Yocto vs Debian library layout.** JetPack/Ubuntu puts the
> libraries in `/usr/lib/aarch64-linux-gnu/` (Debian multiarch). **Yocto
> puts them in `/usr/lib/`** (single-arch). cuDLA is the exception: it
> lives under the CUDA toolkit prefix (`/usr/local/cuda-12.6/lib/`).
> `docker-compose.yml` must bind-mount from source `/usr/lib/...` (host)
> to destination `/usr/lib/aarch64-linux-gnu/...` (where the container
> looks). See the Troubleshooting section and the comments in
> `docker-compose.yml`.

Before flashing the Jetson, confirm the rootfs contains what
`docker-compose.yml` expects to bind-mount. Extract the tegraflash or
inspect the manifest (`*.rootfs.manifest`):

```bash
cd yocto/build/tmp/work/jetson_orin_nano_devkit_nvme-conecsa-linux/conecsa-image/*/rootfs
ls -la usr/lib/libnvinfer.so.10.3.0
ls -la usr/lib/libcudnn.so.9
ls -la usr/lib/libcudnn_cnn.so.9
ls -la usr/lib/libcudnn_ops.so.9
ls -la usr/lib/libnvinfer_plugin.so.10.3.0
ls -la usr/lib/libnvonnxparser.so.10.3.0
ls -la usr/local/cuda-12.6/lib/libcudla.so.1.0.0
ls -la usr/lib/python3/dist-packages/Jetson         # symlink
cat etc/docker/daemon.json                          # nvidia runtime
cat etc/group | grep gpio                           # GID 999

# Realtek PCIe NIC driver (Orin Nano on-board GbE) and network config:
ls -la usr/lib/modules/*/updates/drivers/net/ethernet/realtek/r8168/r8168.ko
cat etc/systemd/network/20-wired.network
cat etc/systemd/timesyncd.conf.d/00-conecsa-ntp.conf

# WiFi (Realtek RTL8822CE): driver, TX-power-limit blob, regdb, supplicant:
ls -la usr/lib/modules/*/updates/drivers/net/wireless/realtek/rtl8822ce/rtl8822ce.ko
ls -la usr/lib/firmware/rtl8822_setting.bin                  # MANDATORY — power init
ls -la usr/lib/firmware/regulatory.db
which usr/sbin/wpa_supplicant || ls usr/sbin/wpa_supplicant
cat etc/systemd/network/30-wireless.network
ls -la etc/wpa_supplicant/wpa_supplicant.conf.example
```

Also confirm in the manifest that the NIC and WiFi packages were pulled in:

```bash
grep -E 'nv-kernel-module-r816|nv-kernel-module-r812|nv-kernel-module-rtl8822|tegra-firmware-rtl8822|wireless-regdb|wpa-supplicant' \
  yocto/build/tmp/deploy/images/jetson-orin-nano-devkit-nvme/*.rootfs.manifest
```

## Flashing the Jetson Orin Nano

> The full procedure, with every failure mode and diagnostic we hit, lives
> in `yocto/FLASHING.md` (runbook). Summary below.

### Build host prerequisites

`initrd-flash` runs on the host and requires:

- `device-tree-compiler` (provides `dtc`) — used by `tegra-flash-helper.sh`
  to sign the bootloader. **Without it the flash aborts immediately**
  (`ERR: 'dtc' command not found`).
- `sgdisk`, `udisksctl`, `tar`, `lsusb` — baseline requirements.
- `bmap-tools` — optional, ~4× faster when writing the rootfs (`dd` is the
  fallback). For a 115 GB but mostly-zero ext4, with bmap the flash takes
  ~3-7 min; without it, ~20 min.

```bash
sudo apt-get install -y device-tree-compiler bmap-tools
```

### Steps

1. Enter recovery: hold FRC + power for 2s, release power.
2. Connect the Jetson to the build host via USB-C (the side port, not the
   power-only one).
3. Confirm enumeration: `lsusb | grep -i "0955:7523"` (NVIDIA Corp APX).
4. Extract the tarball in a working directory and run `initrd-flash` **from
   inside it** (it reads `./.env.initrd-flash` from CWD):

```bash
mkdir -p yocto/jetson-flash && cd yocto/jetson-flash
tar xzf ../build/tmp/deploy/images/jetson-orin-nano-devkit-nvme/conecsa-image-jetson-orin-nano-devkit-nvme.rootfs.tegraflash.tar.gz
sudo ./initrd-flash --erase-nvme
```

`initrd-flash` boots a cboot initramfs on the Jetson via RCM, which
re-exports the NVMe as USB mass storage; the host then writes the
partitions with `sgdisk` + `dd`/`bmaptool`. `--erase-nvme` wipes the old
partition table (recommended on clean flash / layout change). It finishes
with `Final status: SUCCESS`.

After flashing, disconnect the USB-C cable, power the Jetson normally, and
wait for boot. First-boot notes:

- The DisplayPort shows the **hub-vision kiosk** (Weston kiosk-shell) once
  boot reaches `graphical.target`. Until the hub binary is deployed (see
  [Hub kiosk](#hub-kiosk-weston-hub-vision)) the screen stays on the empty
  compositor background — administration is still via serial (debug header)
  or SSH; there is no getty on `tty0`.
- The on-board NIC (`enP8p1s0`, Realtek PCIe) picks up DHCP automatically
  via `systemd-networkd` (config in `20-wired.network`).
- SSH comes up via **socket activation** (`sshd.socket` on `[::]:22`);
  there is no long-running `sshd.service`. SSH is **key-only** (see the SSH
  hardening section) — until you provision a key over serial, SSH refuses
  logins. The **serial console** is the provisioning/recovery channel
  (root, no password).

## Post-flash smoke test

```bash
ssh root@<jetson-ip>                        # key-only — see SSH hardening section
                                            # (or use the serial console for root)

# 1. Expected versions
uname -a                                   # 5.15.x-tegra
cat /etc/nv_tegra_release                  # R36 (release), REVISION: 5.0

# 2. Network (on-board Realtek PCIe NIC)
ip a                                       # enP8p1s0 with DHCP lease
ip route                                   # default via gateway
timedatectl status                         # System clock synchronized: yes

# 3. Docker comes up at boot (enabled by conecsa-bootstrap)
systemctl is-enabled docker.service        # enabled
systemctl is-active docker.service         # active
docker info | grep -i runtime              # shows "nvidia"

# 4. Devices
ls -la /dev/gpiochip0 /dev/gpiochip1 /dev/video0 /dev/nvmap
getent group gpio                          # GID 999

# 5. Kiosk session (Weston + seatd, DisplayPort output)
systemctl get-default                      # graphical.target
systemctl is-active seatd weston           # active / active
journalctl -u weston -b | grep "DP-1"      # DRM head found + output enabled

# 6. Bring up the Conecsa app
cd ~/projects/conecsa-object-detection
docker compose up -d
docker compose ps                          # all Up/healthy
curl http://localhost:5000/api/v1/health   # 200 OK

# 7. Deploy the hub kiosk binary (from the workstation, once per flash)
#    bash scripts/build-hub-jetson.sh
#    → the hub UI appears on the DisplayPort a few seconds later
```

> The containers use `restart: unless-stopped`; because `docker.service` is
> enabled at boot (via `conecsa-bootstrap`, see `FLASHING.md` Step "Docker
> at boot"), the stack comes back on its own after reboot. Without that,
> `docker-moby` only enables `docker.socket` (on-demand activation) and the
> containers do not come back.

## Hub kiosk (Weston + hub-vision)

The image boots straight into a **Wayland kiosk** on the DisplayPort running
the [fleet hub](services/hub-vision.md) — the device can be both a managed
device and the hub of its own fleet. What ships in the image:

| Piece | Recipe | Notes |
|---|---|---|
| Weston 13 (kiosk-shell) | `packagegroup-conecsa-wayland` | DRM backend on the NVIDIA EGL stack (`egl-wayland`) |
| Kiosk config | `recipes-poky-overrides/weston-init` | `weston.ini`: `shell=kiosk-shell.so`, `idle-time=0`, `[autolaunch] path=/usr/bin/hub-kiosk` + `watch=true` |
| seatd daemon | `recipes-poky-overrides/seatd` | poky ships no systemd unit; `seatd -g video` mediates VT/DRM/input for the unprivileged `weston` user |
| webkit2gtk-4.1 runtime | `conecsa-hub-kiosk` RDEPENDS (`webkitgtk3`) | The exact runtime Tauri 2 links; plus `liberation-fonts` |
| Launch wrapper | `conecsa-hub-kiosk` → `/usr/bin/hub-kiosk` | Sets the WebKit/JSC workarounds and `HUB_KEK_FILE`, then execs the hub binary |

The **hub binary is not packaged** — after flashing, deploy it once from the
workstation with `scripts/build-hub-jetson.sh` (builds in an Ubuntu 24.04
arm64 container on the device; glibc and webkit sonames match the image).
Until then the wrapper logs a hint and idles, so the image boots cleanly.

**No-PAM session design** (this distro removes `pam` from `DISTRO_FEATURES`,
so the stock `weston.service` autologin mechanism cannot work — every piece
below was validated live on the device):

- The `weston-init` bbappend drops the stock unit's
  `Requires=systemd-user-sessions.service` (the unit does not exist without
  PAM, and a `Requires=` on a missing unit fails the service) and removes the
  `xwayland` PACKAGECONFIG (the x11 distro feature would inject
  `xwayland=true`, which crashes Weston with no `/tmp/.X11-unix`).
- A systemd drop-in provides `XDG_RUNTIME_DIR` via `RuntimeDirectory=weston`
  and points libseat at the seatd daemon (`LIBSEAT_BACKEND=seatd`) — the
  builtin backend cannot open `/dev/tty0` as non-root.
- `conecsa-image` sets `SYSTEMD_DEFAULT_TARGET = "graphical.target"`
  (weston.service is `WantedBy=graphical.target`; graphical pulls
  `multi-user.target` in, so the Docker stack is unaffected).
- Crash recovery: the hub exiting ends Weston (`watch=true`), and
  `Restart=always` recycles the whole session in a few seconds.

## WiFi connection (Realtek RTL8822CE)

The image bakes the full WiFi stack — driver, firmware blobs, regulatory
database, supplicant, and `systemd-networkd` config. Credentials are **not**
baked in (so SSID/PSK don't leak into image artifacts or git); they are
provisioned at runtime once, after first boot, and persist across reboots.

What is shipped (all in `packagegroup-conecsa-nvidia.bb` /
`conecsa-bootstrap`):

| Component | Package / file | Purpose |
|---|---|---|
| MAC driver | `nv-kernel-module-rtl8822ce` | NVIDIA OoT Realtek driver (registers as PCI driver `rtl88x2ce`) |
| TX power limit blob | `tegra-firmware-rtl8822` → `/lib/firmware/rtl8822_setting.bin` | **Mandatory** — without it the driver's probe aborts with `power init fail` (see Troubleshooting) |
| Standard Realtek firmware | `linux-firmware-rtl8822` → `/lib/firmware/{rtw88,rtlwifi,rtl_bt}/*` | rtw88/rtlwifi firmware + Bluetooth firmware for the combo chip |
| Regulatory database | `wireless-regdb-static` → `/lib/firmware/regulatory.db` | Removes the `cfg80211: failed to load regulatory.db` warning and unlocks regulatory channels |
| Supplicant | `wpa-supplicant` | WPA1/2/3 authentication |
| systemd-networkd config | `/etc/systemd/network/30-wireless.network` (`Match Type=wlan`) | DHCPs any wireless interface, regardless of name (`wlP*`, `wlan0`, etc.) |
| Credentials template | `/etc/wpa_supplicant/wpa_supplicant.conf.example` | Placeholder + inline instructions for the operator |

### First-boot procedure

After the first flash, on the Jetson (serial or `ssh root@<wired-ip>`):

Run these **one line at a time** (do not paste the whole block at once — the
`$IFACE` variable must be set before the lines that use it, and no command
below uses a backslash line-continuation, precisely so a sloppy paste cannot
merge two commands into one):

```bash
# Find the wireless interface name. The kernel names the rtl8822ce on PCIe
# wlP<bus>p<slot>s<func> (e.g. wlP1p1s0 on this hardware).
IFACE=$(ip -o link show | awk -F': ' '/wl/ {print $2; exit}')
echo "Wireless interface: $IFACE"     # must be non-empty before continuing
```
```bash
# Seed wpa_supplicant config from the shipped template (one line).
install -m 0600 /etc/wpa_supplicant/wpa_supplicant.conf.example /etc/wpa_supplicant/wpa_supplicant-$IFACE.conf
```
```bash
# Append the network block via wpa_passphrase (writes a hashed PSK, so the
# cleartext PSK never lands on disk). Quote both args — SSIDs/PSKs often
# contain shell-special chars like % or $.
wpa_passphrase "YOUR_SSID" "YOUR_PSK" >> /etc/wpa_supplicant/wpa_supplicant-$IFACE.conf
```
```bash
# Enable + start the supplicant for that interface — survives reboots.
systemctl enable --now wpa_supplicant@$IFACE
```
```bash
# Verify
sleep 6
iw dev $IFACE link        # → "Connected to <BSSID>" with your SSID
ip a show dev $IFACE      # → an inet address from DHCP
ip route                  # → default route via the wireless interface
```

> If `echo "$IFACE"` prints nothing, stop — the wireless driver isn't binding;
> see the `power init fail` / `Driver: NONE` entries in Troubleshooting. Running
> the `install`/`wpa_passphrase` lines with an empty `$IFACE` is what produces
> the `wpa_supplicant-.conf: No such file or directory` error.

Every subsequent boot: `wpa_supplicant@$IFACE` authenticates automatically,
then `systemd-networkd` DHCPs via the `Type=wlan` match. No manual steps.

### To change networks later

Edit `/etc/wpa_supplicant/wpa_supplicant-$IFACE.conf` (add another
`network={...}` block, or replace the existing one), then:

```bash
systemctl restart wpa_supplicant@$IFACE
```

`wpa_supplicant` will scan, pick the highest-priority reachable network,
and re-associate.

## SSH hardening (key-only, permitted hosts)

The image ships a hardening drop-in at
`/etc/ssh/sshd_config.d/10-conecsa-sshd-hardening.conf` (from
`conecsa-bootstrap`). Because `sshd_config` does
`Include /etc/ssh/sshd_config.d/*.conf` near its top — before the
`debug-tweaks` lines that set `PermitRootLogin yes` / `PermitEmptyPasswords
yes` — and sshd uses the **first** value seen per keyword, the drop-in wins
without editing the generated `sshd_config` or dropping the `debug-tweaks`
image feature. It sets:

```
PasswordAuthentication no
PermitEmptyPasswords no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PubkeyAuthentication yes
PermitRootLogin prohibit-password
```

Net effect: **SSH is key-only**; root may log in over SSH only with a public
key; passwords and empty passwords are refused. The **serial console is
unaffected** and remains the provisioning / recovery channel (root, no
password — `debug-tweaks`).

> Consequence: a freshly flashed device has **no SSH access** until a key is
> provisioned. This is intentional — provision over serial (below). Don't
> lock yourself out by assuming SSH works before the key is in place.

### Provisioning the root key over serial

`/root/.ssh` is pre-created with mode `0700` so sshd won't reject the key for
loose permissions. On the Jetson serial console, paste your public key into
`authorized_keys` — and pin the **permitted hosts** with the `from="..."`
option on the same line (this is where "only permitted hosts" is enforced,
since the key is what grants access):

```bash
# Restrict to a subnet (and/or specific IPs), then the key material:
cat >> /root/.ssh/authorized_keys <<'EOF'
from="172.29.0.0/16,10.0.0.5" ssh-ed25519 AAAAC3Nza...your-key... admin@station
EOF
chmod 600 /root/.ssh/authorized_keys
```

`from=` accepts comma-separated CIDR ranges and IPs (OpenSSH 9.6). Multiple
keys / hosts: add more lines. Verify from an allowed host:

```bash
ssh root@<jetson-ip>          # succeeds with the key, from an allowed host
ssh root@<jetson-ip>          # from a non-listed host → "Permission denied"
```

### Enforcing permitted hosts at the daemon level (optional)

If you prefer the allowed network baked into the image (enforced for every
key, regardless of `from=`), uncomment and edit the `AllowUsers` line in
`meta-conecsa/recipes-conecsa/conecsa-bootstrap/files/10-conecsa-sshd-hardening.conf`:

```
AllowUsers root@172.29.0.0/16
```

then rebuild + reflash. `AllowUsers` takes space-separated `user@CIDR`
entries. The per-key `from=` and daemon-level `AllowUsers` can be combined
(both must pass).

## Measurable targets (vs JetPack 6.2.2 default)

| Metric | JetPack default | Yocto target |
|---|---|---|
| Installed packages | 2245 | ≤ 800 |
| Active systemd services | ~35 | ≤ 20 |
| Boot until `docker.service` active | ~50s | ≤ 25s |
| Free RAM at idle | ~4.9 GiB | ≥ 5.5 GiB |
| Rootfs disk | ~62 GB used | ≤ 30 GB used |

## Troubleshooting

- **`bitbake-layers show-recipes 'nvidia-*'` returns recipes different from
  the ones listed in `packagegroup-conecsa-nvidia.bb`** — meta-tegra
  renames recipes between minor releases. Update the packagegroup with the
  real names and run `bitbake -c cleansstate conecsa-image && bitbake
  conecsa-image`.

- **`do_fetch` of `python3-jetson-gpio` fails because SRCREV is missing** —
  resolve the exact 2.1.9 tag:

  ```bash
  git ls-remote --tags https://github.com/NVIDIA/jetson-gpio.git | grep 2.1.9
  ```

  And replace `SRCREV = "${AUTOREV}"` with the matching SHA.

- **`l4t_initrd_flash` fails because the host has no `udevadm`** — flashing
  requires a Linux x86_64 host with udev running. It does not work on
  macOS or Windows.

- **The Jetson does not enumerate after FRC** — confirm that the USB-C
  cable is on the side port (data), not the bottom one (power only).

- **The app comes up but `inference-service` fails with `libnvinfer.so.10:
  cannot open shared object file`** — the bind-mount in `docker-compose.yml`
  points to the wrong path. On Yocto the libraries live in `/usr/lib/`
  (not `/usr/lib/aarch64-linux-gnu/` like on JetPack). The mount source is
  the Yocto path (`/usr/lib/libnvinfer.so.10.3.0`); the destination is
  where the container looks
  (`/usr/lib/aarch64-linux-gnu/libnvinfer.so.10`). cuDLA is the exception:
  `/usr/local/cuda-12.6/lib/libcudla.so.1.0.0`.

- **`cannot read file data: Is a directory`** on a `.so` bind-mount — the
  source path does not exist on the host, so Docker creates an empty
  directory at the destination. Check the source path (`ls -l` on the host).

- **`error mounting … read-only file system` in the container init** — a
  directory-wide bind-mount (`/usr/lib/aarch64-linux-gnu/nvidia:ro`)
  collides with the per-file injection from `tegra-container-passthrough`.
  Drop the `nvidia`/`tegra` directory mounts from compose; let
  `runtime: nvidia` + passthrough handle them (only TensorRT/cuDNN/cuDLA,
  which passthrough does NOT cover, need an explicit mount).

- **No `eth0` / no physical NIC** — the Orin Nano on-board GbE is a Realtek
  **PCIe** (not the SoC MGBE). `nvethernet.ko` does not work. You need
  `nv-kernel-module-r8168` (+ `nv-kernel-module-r8126`) in
  `packagegroup-conecsa-nvidia.bb`. The in-tree `kernel-module-r8169` and
  `kernel-module-realtek` packages **do not exist** in this L4T kernel
  (`# CONFIG_R8169 is not set`, `CONFIG_REALTEK_PHY=y` builtin).

- **Interface exists but has no IP** — `systemd-networkd` is enabled but
  has no `.network` file. `conecsa-bootstrap` installs
  `/etc/systemd/network/20-wired.network` (DHCP on `eth*`/`en*`).

- **Clock stuck in 1970 / `System clock synchronized: no`** — RTC without a
  battery + missing NTP client. `conecsa-bootstrap` installs
  `systemd-timesyncd` and pins public NTP servers in
  `timesyncd.conf.d/00-conecsa-ntp.conf` (the local LAN advertises an
  unreachable NTP server via DHCP, so we also set `UseNTP=no` in the
  `.network`).

- **`rtl8822ce` module loaded but no `wl*` interface, dmesg shows
  `power init fail`** — the NVIDIA OoT driver's probe is gated on loading
  `/lib/firmware/rtl8822_setting.bin` (the chip's TX-power-limit blob;
  source `hal/hal_com_phycfg.c:4358`, controlled by the
  `CONFIG_HEXFILE_POWER_LIMIT` build flag). The standard
  `linux-firmware-rtl8822` package does **not** ship this file — it lives
  in the NVIDIA BSP, packaged separately as `tegra-firmware-rtl8822`
  (sub-package of `tegra-firmware`). Add `tegra-firmware-rtl8822` to
  `packagegroup-conecsa-nvidia.bb` and re-flash. For an immediate test on
  the running device: `scp` the file from
  `tmp/work/.../tegra-firmware/.../packages-split/tegra-firmware-rtl8822/usr/lib/firmware/rtl8822_setting.bin`
  to `/lib/firmware/` on the Jetson, then `rmmod rtl8822ce && modprobe
  rtl8822ce`.

- **WiFi card driver registered with PCI subsystem (`/sys/bus/pci/drivers/rtl88x2ce/`
  exists) but PCI device shows `Driver: NONE`** — first check
  `dmesg | grep -i 'power init fail'`. If present, see the entry above.
  If absent, try forcing a manual bind:
  `echo 0001:01:00.0 > /sys/bus/pci/drivers/rtl88x2ce/bind`. A `File exists`
  reply from `echo "10ec c822" > .../new_id` means the PCI ID **is** in
  the driver's match table — the binding was rejected later in probe, not
  at the match step.

- **`install: target '/etc/wpa_supplicant/wpa_supplicant-.conf': No such file
  or directory`** — `$IFACE` was empty when the first-boot block was run.
  Either the wireless driver isn't binding (`ip link` has no `wl*` line —
  see entries above) or you ran the variable assignment in a different
  shell. Run the whole first-boot block in **one** shell session so `IFACE`
  is set when the `install` runs.

- **Boot takes ~2 minutes before docker/the stack starts** — check that the
  `systemd-networkd-wait-online` drop-in really **replaces** the stock
  command: it must contain an empty `ExecStart=` line before the new one.
  Without the reset, the drop-in *appends* a second command to the oneshot
  unit and the stock all-links/120 s wait still runs first (paid in full
  whenever a managed link is down, e.g. unplugged Ethernet). With the fix,
  `journalctl -b -u systemd-networkd-wait-online -o short-monotonic` shows
  the unit finishing within ~10 s and docker's API up at ~20 s.

- **`weston.service` fails to start: `Unit systemd-user-sessions.service not
  found`** — the stock unit `Requires=` it, and systemd built without PAM
  does not ship it. The `weston-init` bbappend seds those lines out; on a
  live device, copy the unit to `/etc/systemd/system/` and delete the
  `systemd-user-sessions.service` references.

- **Weston dies with `Could not open target tty: Permission denied` /
  `no drm device found`** — libseat's builtin backend cannot open the VT as
  the non-root `weston` user. The kiosk uses the root `seatd` daemon instead:
  `systemctl is-active seatd` and confirm the weston unit has
  `LIBSEAT_BACKEND=seatd` (drop-in from the `weston-init` bbappend).

- **Weston core-dumps right after `failed to bind to /tmp/.X11-unix/X0`** —
  `xwayland=true` was injected into `weston.ini` (x11 is in
  `DISTRO_FEATURES`). The kiosk is Wayland-only: the `weston-init` bbappend
  removes the `xwayland` PACKAGECONFIG; on a live device delete the line
  from `/etc/xdg/weston/weston.ini`.

- **`webkitgtk3` `do_configure` fails with `GBM is required for USE_GBM`** —
  webkit 2.44 enables `USE_GBM` but on tegra `virtual/egl` is libglvnd, so
  mesa's gbm never reaches the sysroot. The
  `recipes-oe-overrides/webkitgtk3` bbappend adds `DEPENDS +=
  "virtual/libgbm"`.

- **Hub kiosk shows a blank window with `Could not connect to localhost`** —
  the binary was built without `tauri/custom-protocol` (plain `cargo build`),
  which compiles Tauri in dev mode and loads the dev-server URL instead of
  the embedded assets. Always deploy via `scripts/build-hub-jetson.sh` (its
  Dockerfile passes the feature).

- **Hub kiosk shows an empty dark window, no components; audit log has
  `ANOM_ABEND ... exe="/usr/libexec/webkit2gtk-4.1/WebKitWebProcess"
  sig=6`** — JavaScriptCore's WebAssembly JITs (BBQ/OMG) abort on this
  aarch64 build ("Wasm Worklist Helper Thread"), killing the web process as
  soon as the app's WASM starts; there is no message on stderr. The
  `hub-kiosk` wrapper sets `JSC_useBBQJIT=false` and `JSC_useOMGJIT=false`
  (LLInt interprets the wasm). `WEBKIT_DISABLE_DMABUF_RENDERER=1` is also
  set — the DMABUF render path is broken with NVIDIA EGL, while regular
  accelerated compositing works.

- **`do_image_tegraflash` fails with `failed to write conecsa-image.ext4`** —
  the APP partition is smaller than the ext4. Adjust
  `ROOTFSPART_SIZE_DEFAULT` + `TEGRA_EXTERNAL_DEVICE_SECTORS` (see the
  "NVMe partition layout" section).

- **`do_image_tegraflash` fails with pseudo abort / `Permission denied`
  in `tegraflash/signed`** — root-owned leftovers from a previous build
  run as root. Clean with `sudo rm -rf` in the WORKDIR plus `rm` on
  the `conecsa-image` stamps/sstate/sstate-control (details in
  `FLASHING.md` Steps 5a-bis/5a-ter). Always run kas-container as a
  regular user, never via `sudo`.

## Updating NVIDIA versions

When meta-tegra ships a new release (e.g. R36.6 / JetPack 6.3):

1. Update the branch in `kas-config.yml` if needed.
2. Run `kas-container update kas-config.yml`.
3. Confirm recipe names: `kas-container shell kas-config.yml -c
   "bitbake-layers show-recipes 'nvidia-*'"`.
4. Update `packagegroup-conecsa-nvidia.bb` if the names changed.
5. Rebuild: `kas-container build kas-config.yml`.
6. Update the app's README.md to call out the new TRT/cuDNN version on
   major bumps.
