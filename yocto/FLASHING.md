# Flashing runbook — Jetson Orin Nano (NVMe)

Step-by-step procedure to flash `conecsa-image` onto the Orin Nano's NVMe.
Background (build, partition layout, WiFi/SSH provisioning, full
troubleshooting) lives in [`docs/yocto-build.md`](../docs/yocto-build.md);
this file is the operational checklist.

The flash artifact is the self-contained tarball produced by the build:

```
yocto/build/tmp/deploy/images/jetson-orin-nano-devkit-nvme/
└── conecsa-image-jetson-orin-nano-devkit-nvme.rootfs.tegraflash.tar.gz
```

It bundles the flasher itself (`initrd-flash`, `initrd-flash.img`,
`doflash.sh`, `.env.initrd-flash`, signed bootloader binaries) — there is no
standalone `doflash.sh` in the deploy directory.

## Step 1 — Build host prerequisites

Flashing requires a **Linux x86_64 host with udev running** (`initrd-flash`
calls `udevadm`; macOS/Windows do not work).

```bash
sudo apt-get install -y device-tree-compiler bmap-tools
```

- `device-tree-compiler` (`dtc`) — used by `tegra-flash-helper.sh` to sign
  the bootloader. **Without it the flash aborts immediately**
  (`ERR: 'dtc' command not found`).
- `sgdisk`, `udisksctl`, `tar`, `lsusb` — baseline requirements.
- `bmap-tools` — optional but ~4× faster when writing the rootfs (`dd` is
  the fallback). For the ~115 GB mostly-zero ext4: ~3–7 min with bmap,
  ~20 min without.

## Step 2 — Pre-flash validation

Before touching the hardware, confirm the rootfs contains what
`docker-compose.yml` expects to bind-mount (TensorRT/cuDNN/cuDLA paths,
`daemon.json`, gpio group, NIC/WiFi drivers). The full checklist is in
[`docs/yocto-build.md` § Post-build validations](../docs/yocto-build.md#post-build-validations-before-flashing).

## Step 3 — Enter recovery mode

1. Hold **FRC + power** for 2 s, release power.
2. Connect the Jetson to the build host via USB-C — the **side port**
   (data), not the bottom one (power only).
3. Confirm enumeration:

```bash
lsusb | grep -i "0955:7523"      # NVIDIA Corp APX
```

If the Jetson does not enumerate, re-check the cable/port and repeat the
FRC sequence.

## Step 4 — Extract the tarball

`initrd-flash` reads `./.env.initrd-flash` from the current directory, so it
must run **from inside** the extracted tree:

```bash
mkdir -p yocto/jetson-flash && cd yocto/jetson-flash
tar xzf ../build/tmp/deploy/images/jetson-orin-nano-devkit-nvme/conecsa-image-jetson-orin-nano-devkit-nvme.rootfs.tegraflash.tar.gz
```

## Step 5 — Flash

```bash
sudo ./initrd-flash --erase-nvme
```

`initrd-flash` boots a cboot initramfs on the Jetson via RCM, which
re-exports the NVMe as USB mass storage; the host then writes the partitions
with `sgdisk` + `dd`/`bmaptool`. `--erase-nvme` wipes the old partition
table — recommended on a clean flash or whenever the partition layout
changed. A successful run ends with `Final status: SUCCESS`.

If `do_image_tegraflash` failed during the build (the flash artifact is
missing or stale), see the cleanup steps below before rebuilding.

### Step 5a-bis — pseudo abort / `Permission denied` in `tegraflash/signed`

Root-owned leftovers from a previous build that was run as root make
`do_image_tegraflash` fail with a pseudo abort. Clean the image WORKDIR:

```bash
sudo rm -rf yocto/build/tmp/work/jetson_orin_nano_devkit_nvme-conecsa-linux/conecsa-image
```

### Step 5a-ter — clear the image stamps/sstate

After 5a-bis, also remove the `conecsa-image` stamps and sstate control
entries so bitbake regenerates the image from scratch:

```bash
rm -rf yocto/build/tmp/stamps/*/conecsa-image
find yocto/build/sstate-cache yocto/build/tmp/sstate-control -name '*conecsa-image*' -delete 2>/dev/null
```

Then rebuild (`kas-container build kas-config.yml`). **Always run
kas-container as a regular user, never via `sudo`** — that is what creates
the root-owned leftovers in the first place.

## Step 6 — First boot

Disconnect the USB-C cable, power the Jetson normally, and wait for boot:

- The DisplayPort shows the **hub-vision kiosk** (Weston kiosk-shell) once
  boot reaches `graphical.target`. Until the hub binary is deployed
  (`scripts/build-hub-jetson.sh`) the screen stays on the empty compositor
  background; there is no getty on `tty0`.
- The on-board NIC (`enP8p1s0`, Realtek PCIe) picks up DHCP automatically
  via `systemd-networkd`.
- SSH comes up via socket activation and is **key-only** — until a key is
  provisioned over the serial console, SSH refuses logins. The serial
  console (debug header) is the provisioning/recovery channel (root, no
  password). See [`docs/yocto-build.md` § SSH hardening](../docs/yocto-build.md#ssh-hardening-key-only-permitted-hosts).
- WiFi credentials are provisioned once at first boot — see
  [`docs/yocto-build.md` § WiFi connection](../docs/yocto-build.md#wifi-connection-realtek-rtl8822ce).

## Step 7 — Docker at boot

`conecsa-bootstrap` **enables `docker.service`** in the image; combined with
the containers' `restart: unless-stopped` policy, the whole stack comes back
on its own after every reboot. Without it, `docker-moby` only enables
`docker.socket` (on-demand activation) and the containers do not restart at
boot. Verify:

```bash
systemctl is-enabled docker.service        # enabled
systemctl is-active docker.service         # active
docker info | grep -i runtime              # shows "nvidia"
```

## Step 8 — Smoke test

Run the full post-flash smoke test from
[`docs/yocto-build.md` § Post-flash smoke test](../docs/yocto-build.md#post-flash-smoke-test):
expected kernel `5.15.x-tegra`, `/etc/nv_tegra_release` showing
`R36 (release), REVISION: 5.0`, gpio/video/nvmap devices present, seatd +
weston active, then `docker compose up -d` and the health check on
`:5000/api/v1/health`.

## Failure modes quick index

| Symptom | Cause / fix |
|---|---|
| `ERR: 'dtc' command not found` | Install `device-tree-compiler` (Step 1) |
| Flash aborts, host has no `udevadm` | Flash from a Linux x86_64 host with udev |
| Jetson does not enumerate after FRC | USB-C on the side (data) port, not the power-only one |
| `failed to write conecsa-image.ext4` | APP partition smaller than the ext4 — adjust `ROOTFSPART_SIZE_DEFAULT` + `TEGRA_EXTERNAL_DEVICE_SECTORS` ([NVMe partition layout](../docs/yocto-build.md#nvme-partition-layout-critical)) |
| pseudo abort / `Permission denied` in `tegraflash/signed` | Root-owned build leftovers — Steps 5a-bis / 5a-ter |
| Stack doesn't come back after reboot | `docker.service` not enabled — Step 7 |
