//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

/// Role of a header pin, used to colour the cell and label it.
#[derive(Clone, Copy, PartialEq)]
pub(super) enum PinKind {
    Power,
    Ground,
    Trigger,
    Output,
    Other,
}

impl PinKind {
    fn row_class(self) -> &'static str {
        match self {
            PinKind::Trigger => "ui-pin-row ui-pin-row-input",
            PinKind::Output => "ui-pin-row ui-pin-row-output",
            _ => "ui-pin-row",
        }
    }
}

/// A single physical-header pin: number badge + signal name. `flip` mirrors the
/// layout (number on the right) so the right column reads toward the header edge.
#[component]
pub(super) fn PinCell(pin: u8, name: &'static str, kind: PinKind, flip: bool) -> impl IntoView {
    let i18n = use_i18n();
    let num = view! {
        <span class="font-semibold shrink-0">
            {move || t_string!(i18n, settings::pin_number, pin = pin)}
        </span>
    };
    let label = view! { <span class="truncate min-w-0">{name}</span> };
    view! {
        <div class=kind.row_class()>
            {if flip {
                view! { {label} {num} }.into_any()
            } else {
                view! { {num} {label} }.into_any()
            }}
        </div>
    }
}
