//! Leptos UI components for the web frontend.

use leptos::prelude::*;

/// The `StatCard` view component.
#[component]
pub fn StatCard(
    /// Accepts plain `&str` literals (technical tokens like "FPS") and reactive
    /// closures (translated labels are passed as `move || t_string!(...)`).
    #[prop(into)]
    label: TextProp,
    value: Signal<String>,
    children: Children,
) -> impl IntoView {
    view! {
        <div class="ui-list-box p-3 transition-transform hover:-translate-y-1 hover:shadow-md flex flex-col justify-between overflow-hidden h-full min-h-0">
            <div class="flex flex-col gap-1 shrink-0">
                <svg class="w-5 h-5 stroke-primary" viewBox="0 0 24 24" fill="none">
                    {children()}
                </svg>
                <div class="ui-section-title">{move || label.get()}</div>
            </div>
            <div class="ui-value text-2xl font-bold leading-none truncate">{value}</div>
        </div>
    }
}
