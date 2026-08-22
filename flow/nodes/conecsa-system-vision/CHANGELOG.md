# Changelog

## 1.1.1 — 2026-08-22

- Published under the `@conecsa` npm scope:
  `@conecsa/node-red-contrib-conecsa-system-vision`. README and install
  instructions updated; no code changes.

## 1.1.0 — 2026-08-22

First public release on npm.

- **Hub mode.** New `conecsa-hub` configuration node (host, port, API key,
  CA certificate upload, verify) holding the connection to a Conecsa hub's
  Developer API. Every node gained a **Hub** and a **Device** field; with both
  set, requests go to `https://<hub>:<port>/devices/<device>/api/...` carrying
  `X-Api-Key` and trusting the hub CA. Without a hub the nodes keep calling an
  api-gateway directly.
- **"Inference URL" is now "API endpoint"** (same stored property; existing
  flows keep their value). Read-only when a hub is selected.
- **Node type ids are prefixed** `conecsa-` (`conecsa-stats`,
  `conecsa-start-stop`, …) so they cannot collide with other packages. Palette
  labels are unchanged. Flows built with the unprefixed types (1.0.0, only ever
  shipped inside the device image) must be re-imported: export, replace the
  `"type"` values, import.
- HTTP error statuses (401, 403, 503, …) are now reported as node errors
  instead of being parsed as successful replies.
- `detection` tags its payload with the hub device id when no explicit
  device id is configured.
- License: Apache-2.0.

## 1.0.0

Internal release bundled in the Conecsa System Vision device image.
