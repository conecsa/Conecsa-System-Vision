//! Leptos UI components for the web frontend.

use leptos::prelude::*;

/// Usage bar color.
fn usage_bar_color(value: f32) -> &'static str {
    if value < 50.0 {
        "var(--state-success-text)"
    } else if value < 80.0 {
        "var(--state-warning-text)"
    } else {
        "var(--state-danger-text)"
    }
}

/// Usage bar style.
fn usage_bar_style(value: f32) -> String {
    let normalized = if value.is_finite() {
        value.clamp(0.0, 100.0)
    } else {
        0.0
    };
    format!(
        "width: {:.2}%; background-color: {};",
        normalized,
        usage_bar_color(normalized)
    )
}

#[cfg(test)]
mod tests;

#[component]
pub(super) fn MetricCard(
    /// Accepts plain `&str` literals (technical tokens like "CPU") and reactive
    /// closures (translated labels are passed as `move || t_string!(...)`).
    #[prop(into)]
    label: TextProp,
    value: Signal<String>,
    usage: Signal<f32>,
    detail: Signal<String>,
) -> impl IntoView {
    view! {
        <div class="ui-list-box flex flex-col gap-2 p-3">
            <div class="flex items-center justify-between">
                <span class="ui-section-title">{move || label.get()}</span>
                <span class="ui-value text-sm font-bold">{value}</span>
            </div>
            <div class="ui-progress-track">
                <div
                    class="ui-progress-bar"
                    style=move || usage_bar_style(usage.get())
                ></div>
            </div>
            <span class="ui-help">{detail}</span>
        </div>
    }
}
