//! Leptos UI components for the web frontend.

use leptos::prelude::*;

/// The `PanelHeader` view component.
#[component]
pub fn PanelHeader(
    /// Accepts plain `&str` literals and reactive closures (translated titles
    /// are passed as `move || t_string!(...)` so they follow the locale).
    #[prop(into)]
    title: TextProp,
    #[prop(optional)] trailing: Option<AnyView>,
    #[prop(default = true)] margin_bottom: bool,
    children: Children,
) -> impl IntoView {
    let class = if margin_bottom {
        "panel-header panel-header-spaced"
    } else {
        "panel-header"
    };
    view! {
        <div class=class>
            <h2 class="panel-title">
                <svg class="panel-title-icon stroke-current" viewBox="0 0 24 24" fill="none">
                    {children()}
                </svg>
                {move || title.get()}
            </h2>
            {trailing}
        </div>
    }
}
