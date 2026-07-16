//! Leptos UI components for the web frontend.

use leptos::prelude::*;

use crate::class_color::class_display_name;

/// One class chip. `color` is resolved by the caller (which already holds the
/// full class list) — a class with no explicit hex still gets a palette color,
/// so the swatch is always shown rather than misreporting it as colorless.
#[component]
pub(super) fn ClassBadge(index: usize, class_entry: String, color: String) -> impl IntoView {
    let display_name = class_display_name(&class_entry);

    view! {
        <span class="ui-badge ui-badge-primary py-1.5 normal-case">
            <span>{format!("{}. {}", index + 1, display_name)}</span>
            <span
                class="ui-color-swatch"
                style={format!("background-color: {};", color)}
                title={color.clone()}
            />
        </span>
    }
}
