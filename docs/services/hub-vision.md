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
  them (SQLite by default; PostgreSQL or SQL Server configurable),
- **records** every action operators take — on the hub and on its devices — in
  an [audit trail](#audit-trail),
- applies **recipes** — a saved model + thresholds state for the whole fleet, in
  one action, and
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

### Clock synchronization

The hub is also the fleet's **time source**. The Jetson has no RTC battery, and
the image deliberately ignores the DHCP NTP option while pinning public servers —
so on a site with no internet a device boots with a clock at the epoch. Since
certificates carry a validity window (the hub CA starts at 2020-01-01), such a
device rejects the hub's client certificate as *not yet valid*: nginx answers
400, the poller reads that as offline, and the device goes dark **immediately
after a pairing that appeared to succeed** — pairing runs on the TOFU channel,
where nothing is validated, so a wrong clock does not show up there.

The hub therefore relays its own wall clock on the two paths that work:

- **at pairing**, in the `/enroll/complete` body — the one moment a hub can reach
  a device whose clock is wrong. The device adopts it *before* installing the
  certificates, so the flip into enforcing mode already has a valid clock. A
  step the device's agent *refuses* aborts the pairing with nothing installed
  (the hub retries); a host with no hardware agent at all — the x86 development
  stack — pairs anyway, with a warning in the gateway log;
- **afterwards**, in the `X-Conecsa-Hub-Time` header on every status poll. The
  device only honours it on a request the nginx terminator verified, so no other
  container on its compose network can move the clock.

The device applies the time through its privileged `os` agent
(`SetSystemTime`), which refuses anything older than the floor persisted by the
host's `conecsa-fake-hwclock` units — a hub that lost its own time (the kiosk
runs on a Jetson too) can never drag a device backwards. Those same units
restore the floor at boot and save it every 15 minutes and at shutdown, so a
power cut no longer returns the device to 1970. Where there *is* internet,
timesyncd still refines everything on top.

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

## Audit trail

The **Audit** page lists every action a user took, on the hub and on its
devices, in one table: **device**, **event**, **source IP**, **date and time**.
It is **owner/admin only** — hidden from the sidebar and refused by the command
itself, since the trail exists partly to hold operators accountable and the
accounts it audits must not be able to read it.

Filters narrow by device, by period and by free text (username, event key or
target). **Export CSV** writes the current selection — filters applied,
pagination ignored — into the Downloads folder and offers to reveal it.

### Where the actor comes from

The device authenticates nobody: it has no login, no session and no token, and
behind nginx it cannot even see who connected. Its trail is therefore only as
truthful as what the hub puts on the wire. When the hub forwards a request to a
device (see [Opening a device](#opening-a-device)) it stamps the operator's
identity, and the gateway keeps it only when the mTLS terminator verified the
caller. An action nobody could be attributed to is recorded as such rather than
pinned on whoever happened to be signed in.

Hub actions are recorded by the hub itself, against the session it
authenticated. Several hub commands reach a device directly over mTLS rather
than through the UI proxy — applying a recipe, deleting a dataset, pairing — and
those are recorded once, by the hub; the device leaves them alone.

!!! warning "Known limitation"
    Someone talking to a device directly with a valid client certificate would
    produce events with no operator on them. The event is still recorded; the
    actor is anonymous. Closing that would require sessions in the gateway.

### Collection

Devices buffer their own events (see
[api-gateway](api-gateway.md)) and the hub drains them every 5s over mTLS,
paging through `/api/v1/audit/backlog` and acking only after the insert
committed — the same persist-then-ack contract as the
[detection backlog](#offline-coverage-backlog-drain), and the same
device-clock correction, since the hardware has no RTC battery. Delivery is
at-least-once: duplicates are tolerated, losing a record is not.

### Events and language

A row stores a stable event key (`detection.start`, `dataset.deleted`), never a
phrase, so the trail stays language-independent and a hub whose language
changes does not end up with a log written in two of them. The sentence is
composed at render time from the active locale, and the row's target — a
dataset name, an SSID, a model file — is appended after it. A key this hub does
not recognize still renders: a device on a newer build can emit events it has
never heard of, and a blank cell would hide that something happened.

A refused action stays in the table, marked and muted. A rejected sign-in is
often the row that matters.

### Retention

**Settings → Audit retention** sets how many days of history to keep (default
**90**; `0` keeps everything), persisted in `hub-settings.json`. A row expires
on age alone, whether or not it ever reached the operator's reporting database
— a retention promise that silently depended on a remote server having been
reachable would not be one. Changing it is owner/admin only and is itself
audited.

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

## Recipes

A **recipe** names a fleet-wide state: for **every paired device**, which model
to load and which confidence and overlap (IoU/NMS) thresholds to apply. Loading
one puts the whole fleet into that state in a single action, instead of
configuring each device from its own UI.

The **Recipes** page (owner/admin only — loading a recipe reconfigures every
device) lists the stored recipes with a validity badge, and creates or edits
them with one row per paired device: a model picker (populated from that
device's own model list) and the two thresholds, edited to two decimal places.
A new recipe comes **pre-filled with each device's current values**, so saving
one straight away captures the fleet as it is today.

### Validity

Every time the page loads it snapshots the fleet (`/api/v1/status` and
`/api/v1/models` on each paired device, in parallel) and re-checks each recipe
against it. A recipe is marked **INVALID** — with the reason in the badge's
tooltip, and its **Load** action disabled until it is edited — when:

- a device that is **online** no longer has the recipe's model,
- **no model was chosen** for a device — a device that was offline when the
  recipe was saved has no model list to pick from, so the recipe is stored
  without one rather than refusing the save (otherwise a single unreachable
  device would block every recipe from being created),
- the recipe names a device this hub is **no longer paired** with, or
- a device was **paired after** the recipe was saved, so the recipe does not
  cover it. Opening **Edit** pre-fills the new device's row with its current
  values, so saving fixes it.

A device that is merely **offline** does not, by itself, invalidate a recipe:
its model list is *unknown*, not empty, so a *missing* model cannot be
asserted. It shows up instead as a failed device when the recipe is loaded.

### Loading

**Load** confirms first, then applies to all of the recipe's devices in
parallel and reports **one outcome per device** — a device that is offline or
refuses never aborts the others. The backend re-validates against a fresh
snapshot before applying (the UI gate is not the only one) and re-checks the
model on the device immediately before selecting it.

Per device the order is fixed:

1. `POST /api/v1/model/select` — **skipped when the model is already active**,
   since re-selecting it would deserialize the TensorRT engine again for no
   change.
2. `POST /api/v1/overlay_threshold`.
3. `PUT /api/v1/config` with `confidence_threshold`.

The model comes first because selecting it repoints the device at that model's
`<model>.settings.json` and applies the thresholds stored there — thresholds
written before the switch would be overwritten. Confidence goes through
`/api/v1/config` rather than `/api/v1/threshold` because the latter only
mutates the device's memory and is lost on restart, while the config route
persists (see
[inference-service](inference-service.md)).

Recipes live in `recipes.json` in the app config directory, next to
`hub-settings.json`.

## Opening a device

**Open** embeds a device's main page — its UI, REST/MJPEG/SSE API and the Flow
editor — inside the hub. The hub serves it through a per-device `127.0.0.1`
reverse proxy that forwards every request (including the Node-RED websocket) to
the device's `:443` over the mTLS channel, so the webview reaches the device
through a plain-localhost origin with no certificate prompt while the device stays
reachable only by the hub. The hub also appends `?lang=<locale>` to the iframe
URL, so the embedded device UI opens in the hub's language (see
[Localization](#localization)).

Every forwarded request carries the signed-in operator's identity —
`X-Conecsa-User`, `X-Conecsa-Role` and `X-Conecsa-Origin-Ip` — which is how
device-side actions get an actor at all (see [Audit trail](#audit-trail)). The
headers are cleared before being written, so a page being proxied cannot claim
to be someone else: an unauthenticated request arrives with no identity rather
than a forged one.

## Developer API

Because devices answer only to the hub, nothing else on the network can call a
device's api-gateway — until an admin opens the hub's **Developer API**
(**Settings → Developer**, owner/admin only, off by default). With **Accept
requests** on, the hub listens on every IPv4 interface (`0.0.0.0`; IPv6 is not
served — HTTPS, port `8443` by default, editable) and forwards requests to any
paired device:

```
GET  https://<hub-ip>:8443/devices                      paired devices (JSON: id, name, ip, online, running, version, last_seen)
*    https://<hub-ip>:8443/devices/<device_id>/api/...  forwarded to the device's api-gateway
```

Every request must carry `X-Api-Key: <key>`. The key is minted (64 hex
characters, 256 bits of randomness; anything shorter than 16 characters is
refused outright) the first time the API is turned on, shown in the Developer
section, and can be **rotated** there — the old key stops working on the next
request. It is stored in the encrypted secret store next to the CA key; it is
compared in constant time, never logged, and stripped before the request leaves
the hub. A wrong or missing key gets `401`, an unpaired device id `404`, an
offline device `503`.

Only `/api/...` is forwardable (the api-gateway surface: `/api/v1/*` and the
legacy `/api/*` aliases). `/enroll/*` — which can reset a device's pairing —
`/flow/*` and the UI shell are not reachable this way; a path with a `.` or
`..` segment (raw or percent-encoded), which the device's nginx would
normalize out of `/api`, is refused with `400`. Bodies are piped in both
directions, so MJPEG (`/api/v1/video_feed*`), SSE (`/api/v1/events/stream`),
uploads and downloads all work; websocket upgrades are not supported (the
api-gateway has none). Each live stream pins a worker thread on the device, so
fan out streams with care.

The listener's certificate is issued by the hub's own CA on every start, with
the hub's LAN IPv4 addresses as subject alternative names, so `https://<ip>:8443`
validates once the client trusts the CA. **Download CA certificate** in the
Developer section saves `conecsa-hub-ca.crt` (PEM) for that:

```bash
curl --cacert conecsa-hub-ca.crt -H "X-Api-Key: $KEY" https://192.168.1.10:8443/devices
curl --cacert conecsa-hub-ca.crt -H "X-Api-Key: $KEY" \
     https://192.168.1.10:8443/devices/<device_id>/api/v1/status
curl --cacert conecsa-hub-ca.crt -H "X-Api-Key: $KEY" -X POST \
     https://192.168.1.10:8443/devices/<device_id>/api/v1/start
```

Node-RED users need no curl: the
[`@conecsa/node-red-contrib-conecsa-system-vision`](https://www.npmjs.com/package/@conecsa/node-red-contrib-conecsa-system-vision)
package (the same nodes the device's Flow ships, see [Flow](flow.md#connecting-the-nodes))
has a `conecsa-hub` configuration node that takes this URL, key and CA file and
lets every node pick a paired device from the hub's list.

Forwarded requests reach the device over the same mTLS channel as the
operator's, stamped as user `api-key` with the `admin` role (so every
api-gateway route is reachable — the key is the whole boundary) and with the
caller's IP as `X-Conecsa-Origin-Ip`, which is what the device's
[audit trail](#audit-trail) then shows. Turning the API on or off, rotating
the key and changing the port are audited on the hub. The API runs as long as
the hub app is running and the toggle is on; it does not depend on anyone
being signed in.

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
**Generate schema** (DDL, which creates `devices`, `detections` and
`audit_events`):

| Backend | Notes |
|---|---|
| SQLite | Default; no configuration needed. |
| PostgreSQL | Built in by default. |
| SQL Server | Requires building with the `mssql` feature (tiberius) — see below. |

Two stores sit beside that one under the app data directory and are never
reconfigurable: `auth.db` (operator accounts) and `audit.db` (the
[audit trail](#audit-trail)). The trail is deliberately local: the configured
database can be repointed from Settings, be unreachable, or not be set up yet,
and none of that may cost an audit record. Rows are mirrored into the
configured database for reporting, best-effort and write-only — the UI always
reads `audit.db`, and a mirror failure leaves rows pending rather than losing
them.

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
