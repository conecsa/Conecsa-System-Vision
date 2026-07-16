//! Locale resolution and persistence.
//!
//! The device UI has no language selector of its own: the hub appends
//! `?lang=<locale>` to the embed iframe URL, and direct browser access falls
//! back to the last locale persisted in localStorage. When neither is present,
//! leptos_i18n's own CSR init resolves `navigator.languages` → default (`en`).

use leptos::prelude::*;
use leptos_i18n::Locale as _;

use crate::i18n::{use_i18n, Locale};

/// localStorage key holding the last effective locale.
const LANG_KEY: &str = "conecsa.lang";

/// Explicit locale requested for this page load: `?lang=` (hub embed) first,
/// then localStorage. Parsing is strict (`FromStr`), so an invalid `?lang=`
/// falls through to the stored value instead of silently becoming `en`.
fn explicit_locale() -> Option<Locale> {
    let window = web_sys::window()?;

    let search = window.location().search().ok()?;
    if let Ok(params) = web_sys::UrlSearchParams::new_with_str(&search) {
        if let Some(lang) = params.get("lang") {
            if let Ok(locale) = lang.parse::<Locale>() {
                return Some(locale);
            }
        }
    }

    let stored = window.local_storage().ok()??.get_item(LANG_KEY).ok()??;
    stored.parse::<Locale>().ok()
}

/// Apply the explicit locale (if any) and keep localStorage in sync with every
/// effective locale change. Must run inside `I18nContextProvider`.
pub fn init_locale() {
    let i18n = use_i18n();
    // The provider's own init effect resolves `navigator.languages` into the
    // locale signal AFTER the initial render, so a `set_locale` done
    // synchronously here (component body) would be clobbered by it. Applying
    // ours inside an Effect created after the provider's guarantees it runs
    // later in the same flush and wins.
    let explicit = explicit_locale();
    Effect::new(move |_| {
        if let Some(locale) = explicit {
            i18n.set_locale(locale);
        }
    });
    Effect::new(move |_| {
        let locale = i18n.get_locale();
        if let Some(Ok(Some(storage))) = web_sys::window().map(|w| w.local_storage()) {
            let _ = storage.set_item(LANG_KEY, locale.as_str());
        }
    });
}
