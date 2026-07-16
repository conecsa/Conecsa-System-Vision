//! Role resolution and persistence (mirrors `locale.rs`).
//!
//! The device UI has no login of its own: the hub appends `?role=admin|user`
//! to the embed iframe URL (owner is mapped to admin hub-side), and direct
//! browser access falls back to the last role persisted in localStorage. When
//! neither is present the UI fails closed (restricted). This is UI-only
//! gating — the device API itself does not enforce it.

use leptos::prelude::*;

/// localStorage key holding the last effective role.
const ROLE_KEY: &str = "conecsa.role";

/// Whether the current session may use privileged controls.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Privileged(pub bool);

/// Strict parse, like locale's `FromStr`: unknown values fall through to the
/// next source instead of silently granting or revoking access.
fn parse_role(role: &str) -> Option<bool> {
    match role {
        "admin" => Some(true),
        "user" => Some(false),
        _ => None,
    }
}

/// Explicit role requested for this page load: `?role=` (hub embed) first,
/// then localStorage.
fn explicit_privileged() -> Option<bool> {
    let window = web_sys::window()?;

    let search = window.location().search().ok()?;
    if let Ok(params) = web_sys::UrlSearchParams::new_with_str(&search) {
        if let Some(role) = params.get("role") {
            if let Some(privileged) = parse_role(&role) {
                return Some(privileged);
            }
        }
    }

    let stored = window.local_storage().ok()??.get_item(ROLE_KEY).ok()??;
    parse_role(&stored)
}

/// Resolve the role, persist it, and provide [`Privileged`] as context. Unlike
/// `init_locale` there is no competing writer, so this resolves synchronously.
/// Must run in a component body above every consumer (i.e. in `App`).
pub fn init_access() {
    let privileged = explicit_privileged().unwrap_or(false);
    if let Some(Ok(Some(storage))) = web_sys::window().map(|w| w.local_storage()) {
        let _ = storage.set_item(ROLE_KEY, if privileged { "admin" } else { "user" });
    }
    provide_context(Privileged(privileged));
}

/// Consumer helper; fails closed when the context is missing.
pub fn privileged() -> bool {
    use_context::<Privileged>().map(|p| p.0).unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;
    use wasm_bindgen_test::*;

    wasm_bindgen_test_configure!(run_in_browser);

    #[wasm_bindgen_test]
    fn parse_role_is_strict() {
        assert_eq!(parse_role("admin"), Some(true));
        assert_eq!(parse_role("user"), Some(false));
        assert_eq!(parse_role("owner"), None);
        assert_eq!(parse_role("Admin"), None);
        assert_eq!(parse_role(""), None);
    }
}
