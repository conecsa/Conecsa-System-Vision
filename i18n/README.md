# Translation catalogs

Shared i18n catalogs for the two Leptos frontends, consumed at compile time by
`leptos_i18n_build` from each crate's `build.rs`:

- `system-vision/` — namespaced catalogs (`<locale>/<namespace>.json`), one JSON
  per feature area: `common`, `main`, `control_panel`, `stream`, `models`,
  `camera`, `settings`, `training`, `statistics`, `flow`. Access in code:
  `t!(i18n, <namespace>::<key>)`.
- `hub-vision/` — one file per locale (`<locale>.json`) with nested sections:
  `common`, `sidebar`, `auth`, `devices`, `records`, `users`, `settings`.
  Access in code: `t!(i18n, <section>.<key>)`.

Locales: `en` (default / source of truth), `pt-BR`, `es`. Every key must exist
in `en`; a key missing from `pt-BR`/`es` falls back to the English value and
emits a build warning — keep the three locales at full parity. Values support
interpolation with `{{ name }}` placeholders (avoid `<`/`>` in values: angle
brackets are parsed as component interpolation).

The device UI (system-vision) has no language selector: the hub appends
`?lang=<locale>` to the embed iframe URL and the app persists the choice in
localStorage. The only selector lives in hub-vision → Settings → Language.

## Glossary

Keep these terms identical across both apps:

| en | pt-BR | es |
|---|---|---|
| Detection | Detecção | Detección |
| Device | Dispositivo | Dispositivo |
| Model | Modelo | Modelo |
| Training | Treinamento | Entrenamiento |
| Records | Registros | Registros |
| Settings | Configurações | Configuración |
| Class | Classe | Clase |
| User | Usuário | Usuario |
| Password | Senha | Contraseña |
| Pair / Unpair | Parear / Desparear | Emparejar / Desemparejar |
| Connect / Disconnect | Conectar / Desconectar | Conectar / Desconectar |
| Threshold | Limiar | Umbral |
| Upload | Enviar | Subir |
| Download | Baixar | Descargar |
| Save / Cancel / Delete | Salvar / Cancelar / Excluir | Guardar / Cancelar / Eliminar |
| Live Stream | Transmissão ao Vivo | Transmisión en Vivo |
| Camera | Câmera | Cámara |
| Network | Rede | Red |

Never translated: brand/product names (CONECSA, Hub Vision, Node-RED,
PostgreSQL, TensorRT, YOLO, SAM), technical tokens (GPU, CPU, RAM, FPS, ms,
MB, IP, DHCP, SSID, GPIO), backend enum/status values compared or sent over
the API, and the language selector's option labels (each language names
itself).
