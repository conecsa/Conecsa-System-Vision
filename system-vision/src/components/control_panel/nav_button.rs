//! Leptos UI components for the web frontend.

use leptos::prelude::*;

/// A `ViewMode` enum.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ViewMode {
    LiveStream,
    CameraSettings,
    Flow,
    Settings,
    /// Full-page training view (replaces the dashboard). Entered only through
    /// the confirmation modal — stopping inference is a side effect — so there
    /// is no plain NavButton for it.
    Training,
}

/// The `NavButton` view component.
#[component]
pub fn NavButton(
    view_mode: ViewMode,
    current_view: ReadSignal<ViewMode>,
    set_current_view: WriteSignal<ViewMode>,
    /// Accepts plain `&str` literals and reactive closures (translated titles
    /// are passed as `move || t_string!(...)` so they follow the locale).
    #[prop(into)]
    title: TextProp,
    /// Same contract as `title`.
    #[prop(into)]
    label: TextProp,
    /// Renders the button greyed out and inert (used for role gating).
    #[prop(optional)]
    disabled: bool,
    children: Children,
) -> impl IntoView {
    view! {
        <button
            class={move || {
                if current_view.get() == view_mode {
                    "nav-button nav-button-active disabled:opacity-50 disabled:cursor-not-allowed"
                } else {
                    "nav-button disabled:opacity-50 disabled:cursor-not-allowed"
                }
            }}
            disabled=disabled
            on:click=move |_| set_current_view.set(view_mode)
            title=move || title.get()
        >
            <svg
                class="nav-button-icon stroke-current"
                viewBox="0 0 24 24"
                fill="none"
            >
                {children()}
            </svg>
            <span class="nav-button-label">{move || label.get()}</span>
        </button>
    }
}
