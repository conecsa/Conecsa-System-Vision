# Fleet hub (`hub-vision`)

`conecsa-hub-vision` is a native (Tauri 2 + Leptos) desktop **hub** for a fleet
of `conecsa-system-vision` devices (Jetsons). It is **not** part of the
`docker-compose` stack and **not** containerized — it is built separately (see
[Build](#build)) and installed on a hub machine that sits on the same LAN as the
devices. It can also run **on a Jetson itself**, auto-started at boot as a
Wayland kiosk on the DisplayPort (see
[Jetson kiosk deployment](#jetson-kiosk-deployment)).

It is the single authenticated, secure entry point to the fleet. It does **not**
drive the devices directly. Instead it:

- **authenticates** operators (login required for every action),
- **discovers** devices on the LAN via mDNS (`_conecsa._tcp`),
- **pairs** with each device — acting as a private CA — and then reaches it **only
  over mutual TLS** (no plaintext; no root certificate installed on the hub),
- **pulls** their detection records by polling each device over mTLS and **stores**
  them (SQLite by default; PostgreSQL or SQL Server configurable), and
- lets you **open each device's main page** inside the hub (an embedded iframe
  pane — no external browser, the same way the device UI embeds the Flow editor).

## Authentication & security

On first run the hub seeds a default `admin` account (forced password change on
first login); every action requires a login session. Sessions use a **sliding
12-hour expiry**: every authenticated action renews the window, so an active
operator is never signed out mid-shift — the session only lapses after 12 hours
of inactivity, at which point the UI returns to the login screen automatically
(detection collection is unaffected; it runs independently of the session). A
hidden built-in `conecsa` service account also exists (never stored in the
database), but its sign-in is gated behind the `CONECSA` environment variable
and **disabled by default**.

On first setup the hub also generates a private **Certificate Authority**. To
bring a device under management you **pair** it — one click when it appears under
**Devices** on a trusted LAN (set `DEVICE_PAIR_TOKEN` on the device to require a
shared secret). Pairing signs the device's certificate with the hub CA; from then
on the hub reaches the device **only over mutual TLS**, presenting its own
hub-signed client certificate and trusting the CA programmatically — so **no root
certificate is installed** on the hub machine. Once paired, a device is locked to
that hub until it is unpaired.

### Device identity

A device's identity is its **hostname** (`conecsa-<serial>`, assigned on first
boot by `conecsa-set-hostname`). Enrollment puts it in the certificate SAN
(`device-<id>.conecsa.local`), and the hub keys its paired-set — and every mTLS
call — by it.

The mDNS *instance name* is not that identity: avahi renames a colliding instance
(`conecsa-x` → `conecsa-x-2`), which happens on a stale record after an IP change
or when two devices share a hostname. So the device states its identity outright,
in the `device_id` TXT record of its advertisement, and the hub treats the
instance name as a fallback only — reconciling it against `/enroll/info`, which is
authoritative, and re-keying the device when the two disagree.

Left unreconciled, that mismatch is a trap: the device would be keyed by a name
its certificate does not carry, so it would read as *unpaired* forever while every
mTLS call failed the SAN check — and the pairing UI would report it as paired to
another hub, with no way out from the hub side.

## Detection pull

The hub **pulls** detections; there is no inbound ingestion server. For each
paired, online device it polls `/api/v1/detections/snapshot` over mTLS, de-dupes,
and stores new records (only when the detection total is greater than zero).
Collection runs in the background whenever the hub app is open, independent of the
login session.

Records store the **clean** frame (no overlay) plus each detection's
normalized bbox coordinates: when the cheap poll shows the device reports
`bbox`, the full fetch asks for `raw_frame` instead of the annotated frame
(still one JPEG per record). The Records preview redraws the boxes
client-side over the image. Devices running an older firmware keep working —
their records store the annotated frame and render with no overlay.

### Offline coverage (backlog drain)

Detection changes that happen while the hub is closed or unreachable are not
lost: the device buffers them on disk (see the
[inference-service offline buffer](inference-service.md)) and the snapshot
advertises the pending count. When the collector sees `pending_backlog > 0` it
drains the backlog first — paging through `/api/v1/detections/backlog` (25
records per page, byte-trimmed by the device with a ~3MB stored-bytes soft cap
(after the first record) so pages typically stay within transport limits, up to 40 pages per 1s cycle), inserting each page
**transactionally into the store** and acking only after the insert commits,
so the device deletes a record only once the hub has durably persisted it. A
failed insert or ack simply retries on the next cycle. Each record's
`received_at` is reconstructed from its device-side capture age
(`device_now - captured_at`, both from the device's clock, so any absolute
clock error cancels): the offline window appears spread over real time in the
Records page, not collapsed at the reconnection instant. The last drained
record seeds the collector's dedup signature, so the live snapshot that
matches it is not recorded twice.

### Records → dataset (model improvement)

When the model detects something incorrectly, that record is exactly what the
next training round needs. Records that carry coordinates offer an **Add to
dataset** action (owner/admin only — it writes into a device dataset): pick a
paired device and one of its datasets, and the hub
ships the clean image to the device's pre-labeled ingest route
(`POST /api/v1/training/datasets/<id>/images`). The detection coordinates
become the image's YOLO labels (letterboxed device-side; class names are
resolved or created on the dataset), so in the device's label editor the
operator only fixes the class — no re-drawing. Legacy records (annotated
frame, no coordinates) cannot be exported.

## Datasets

The **Datasets** page (owner/admin only) lists every dataset on every paired,
online device, grouped per device — each shown as the same cover-image card
the device UI uses (covers travel over the mTLS channel; a device that fails
to answer shows an inline error in its own group without affecting the
others). Clicking a card opens a **read-only image gallery** of the dataset:
thumbnails are fetched over mTLS page by page (24 at a time), and labeled
images show their box count. Datasets are not editable from the hub; the card
actions are:

- **Download** — saves the dataset's export ZIP (images + labels +
  `data.yaml`) into the local Downloads folder (the home directory on the
  kiosk, which has none).
- **Delete** — removes the dataset from its device, after a confirmation
  modal. A dataset locked by a running training job is refused by the device
  (the message is shown in the modal).
- **Transfer** — copies the dataset to another paired device by exporting the
  ZIP and re-importing it there under the same name (the device-side upload
  cap, `TRAINING_MAX_UPLOAD_MB` / 512 MB by default, applies). The target
  mints a fresh dataset id and new image ids; classes and labels are
  preserved, the cover falls back to the oldest image, and same-name
  duplicates are allowed. An optional checkbox removes the source copy — only
  after the import is confirmed; if that removal fails, the transfer still
  succeeds and reports a warning.

## Opening a device

**Open** embeds a device's main page — its UI, REST/MJPEG/SSE API and the Flow
editor — inside the hub. The hub serves it through a per-device `127.0.0.1`
reverse proxy that forwards every request (including the Node-RED websocket) to
the device's `:443` over the mTLS channel, so the webview reaches the device
through a plain-localhost origin with no certificate prompt while the device stays
reachable only by the hub. The hub also appends `?lang=<locale>` to the iframe
URL, so the embedded device UI opens in the hub's language (see
[Localization](#localization)).

## Federated training

The **Training** page (owner/admin only) trains one YOLO model across **every
paired device** with federated averaging — no central GPU and no
device-to-device traffic; the hub ferries opaque `.pt` blobs over the existing
per-device mTLS channel. The operator picks the source device + dataset,
rounds and epochs per round; a confirmation modal warns that **object
detection stops on the whole fleet** (the same gate as the device UI's
training entry) and lists the participants.

The coordinator (the `src/federated/` module) then drives one job at a time
through phases the page polls every second:

1. **entering** — GPU handover (`/training/enter`) on every participant.
2. **sharding** — exports N deterministic IID shards from the source device
   and imports one into each participant.
3. **training / collecting / averaging** (per round) — each device trains E
   local epochs from the shared weights (round 1 starts from the identical
   baked-in base weights), the hub collects each `last.pt`, ships them to the
   aggregator (the source device) for CPU averaging, and redistributes the
   averaged checkpoint.
4. **finalizing** — uploads the final averaged model to **every** participant
   through the regular model route (pt→onnx→engine conversion), deletes the
   shard datasets and exits training mode (runtime stays released while the
   conversion runs, as after a device-local training).

Preflight requires every paired device online (synchronous FedAvg needs all
participants), at least two of them, and a dataset large enough that each
shard still passes the device training gates (≥ 20 images and ≥ 2 labeled per
shard). On failure or cancel the coordinator best-effort cancels device jobs
and resumes the inference runtimes; stale weight blobs are pruned device-side
by TTL. See [training-service](training-service.md#federated-training-hub-orchestrated-fedavg)
for the device-side building blocks.

## Discovery

Devices advertise `_conecsa._tcp.local.` from the **host** `avahi-daemon`
(provisioned by `meta-conecsa/recipes-conecsa/conecsa-bootstrap`), which reaches
the LAN. The api-gateway also ships an in-container python-zeroconf advertiser,
but it is **disabled** (`HUB_MDNS_ENABLED=0`) because the container is on a
docker bridge and would only announce its unreachable bridge IP.

The hub browses passively and lists discovered devices under **Devices**.
**Open** embeds that device's main page in the hub.

## Storage

SQLite is the default (a file under the app data directory). External backends
are configured in **Settings**, each with **Test connection** (health check) and
**Generate schema** (DDL):

| Backend | Notes |
|---|---|
| SQLite | Default; no configuration needed. |
| PostgreSQL | Built in by default. |
| SQL Server | Requires building with the `mssql` feature (tiberius) — see below. |

## Localization

The UI is available in **English** (default), **Brazilian Portuguese** and
**Spanish**. The language selector lives in **Settings → Language**; switching
applies instantly and the choice is persisted in `hub-settings.json` (it is
read pre-auth, so the login screen already renders localized). Date/time
formatting follows the active language. The selection also propagates to every
embedded device page via `?lang=` on the iframe URL — the device UI persists it
in localStorage, so it keeps the language even when opened directly in a
browser. Translations are compiled in from the repo-root `i18n/hub-vision/`
catalogs (see `i18n/README.md` for the layout and the shared glossary).

## Build

The hub is built from the repo root with `scripts/build-hub.sh` — it builds the
Tailwind CSS, the Leptos/WASM webview (Trunk → `hub-vision/dist`), then bundles
the desktop app with `cargo tauri build` (output under
`target/release/bundle/`):

```bash
# from the repo root
bash scripts/build-hub.sh                        # SQLite + PostgreSQL backends
HUB_FEATURES=mssql bash scripts/build-hub.sh     # also include SQL Server (tiberius)
```

Dev loop:

```bash
cd hub-vision && cargo tauri dev   # runs `trunk serve` for the webview
```

See `hub-vision/README.md` for additional detail.

## Jetson kiosk deployment

The hub also runs on the device itself, shown fullscreen on the DisplayPort
from boot. The Yocto image ships the session (Weston kiosk-shell + seatd +
the webkit2gtk-4.1 runtime + the `/usr/bin/hub-kiosk` wrapper — see
[Yocto build](../yocto-build.md#hub-kiosk-weston-hub-vision)); the binary
itself is **not** packaged in the image. Build and deploy it from the
workstation:

```bash
# Builds inside an Ubuntu 24.04 arm64 container ON the device (via the
# docker context) and installs the binary to /usr/local/bin on the host.
bash scripts/build-hub-jetson.sh
# Knobs: DOCKER_CONTEXT (default conecsa-system-vision), HUB_DEVICE (ssh
# destination, derived from the context endpoint), CARGO_BUILD_JOBS
# (default 4), HUB_FEATURES (e.g. mssql).
```

Ubuntu 24.04 matches the Yocto host's glibc (2.39) and the
webkit2gtk-4.1/gtk3/libsoup3 sonames, so the dynamically linked binary runs
directly on the host — no container at runtime. BuildKit cache mounts on the
device keep rebuilds incremental; the script verifies dynamic linking with the
glibc loader and recycles the kiosk session after installing.

Kiosk specifics:

- **Session/user**: the app runs as the `weston` user, launched by Weston's
  `[autolaunch]` (kiosk-shell fullscreens it). A crash recycles the whole
  session (`watch=true` + `Restart=always`), back in a few seconds.
- **State** lives under `/home/weston/.config|.local/share/com.conecsa.hub-vision/`.
  **Back it up before re-flashing** (KEK + `secrets.bin` + `*.db`), or pairing
  state is lost.
- **Secrets without a keychain**: the minimal image has no Secret Service, so
  the hub falls back to a file-based KEK (`kek.bin`, mode 0600) for
  `secrets.bin`; the wrapper pins the path via `HUB_KEK_FILE`. Desktop installs
  keep using the OS keychain.
- **Self-management**: the kiosk hub discovers the device it runs on via mDNS
  like any other device (multicast loopback), so a single Jetson can be both a
  managed device and the fleet hub.
- **WebKit workarounds** (set by the wrapper, root-caused on the device):
  `WEBKIT_DISABLE_DMABUF_RENDERER=1` (DMABUF path broken with NVIDIA EGL) and
  `JSC_useBBQJIT=false` / `JSC_useOMGJIT=false` (the wasm JITs SIGABRT on this
  aarch64 build; LLInt interpretation is stable).
