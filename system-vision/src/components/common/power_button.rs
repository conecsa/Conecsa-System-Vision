//! Leptos UI components for the web frontend.

use leptos::prelude::*;
use leptos::task::spawn_local;

use crate::api::system_power;
use crate::i18n::*;

/// Which action the user has selected.
#[derive(Clone, Copy, PartialEq)]
enum PowerAction {
    Shutdown,
    Restart,
}

impl PowerAction {
    /// Localized label (tracked — re-renders on locale switch).
    fn label(self, i18n: leptos_i18n::I18nContext<Locale>) -> &'static str {
        match self {
            Self::Shutdown => t_string!(i18n, common::shutdown),
            Self::Restart => t_string!(i18n, common::restart),
        }
    }
    /// Localized confirmation question.
    fn confirm_msg(self, i18n: leptos_i18n::I18nContext<Locale>) -> &'static str {
        match self {
            Self::Shutdown => t_string!(i18n, common::shutdown_confirm),
            Self::Restart => t_string!(i18n, common::restart_confirm),
        }
    }
    /// Api action.
    fn api_action(self) -> &'static str {
        match self {
            Self::Shutdown => "shutdown",
            Self::Restart => "restart",
        }
    }
}

/// Internal state machine for the button.
#[derive(Clone, Copy, PartialEq)]
enum ButtonState {
    /// Show the power icon button.
    Idle,
    /// Dropdown is open — choose shutdown or restart.
    Menu,
    /// Confirm the selected action before sending.
    Confirm(PowerAction),
    /// Request in flight.
    Executing,
    /// Request completed (success / error).
    Done(bool),
}

/// A header button that lets the operator shut down or restart the controller.
///
/// Renders a small power icon on the right side of the header. Clicking it
/// opens an inline dropdown where the operator chooses *Restart* or
/// *Shutdown*, then confirms once more before the command is sent.
#[component]
pub fn PowerButton() -> impl IntoView {
    let i18n = use_i18n();
    let state = RwSignal::new(ButtonState::Idle);

    // Close the menu/confirm if the user clicks elsewhere in the document.
    let on_global_click = move |_: web_sys::MouseEvent| {
        let s = state.get_untracked();
        if matches!(s, ButtonState::Menu | ButtonState::Confirm(_)) {
            state.set(ButtonState::Idle);
        }
    };
    let _ = window_event_listener(leptos::ev::click, on_global_click);

    let on_power_click = move |ev: web_sys::MouseEvent| {
        ev.stop_propagation();
        state.update(|s| {
            *s = match *s {
                ButtonState::Idle => ButtonState::Menu,
                ButtonState::Menu => ButtonState::Idle,
                _ => ButtonState::Idle,
            };
        });
    };

    let on_action_click = move |action: PowerAction| {
        move |ev: web_sys::MouseEvent| {
            ev.stop_propagation();
            state.set(ButtonState::Confirm(action));
        }
    };

    let on_confirm_click = move |ev: web_sys::MouseEvent| {
        ev.stop_propagation();
        let action = match state.get_untracked() {
            ButtonState::Confirm(a) => a,
            _ => return,
        };
        state.set(ButtonState::Executing);

        spawn_local(async move {
            let ok = system_power(action.api_action()).await.is_ok();
            state.set(ButtonState::Done(ok));
        });
    };

    let on_cancel_click = move |ev: web_sys::MouseEvent| {
        ev.stop_propagation();
        state.set(ButtonState::Idle);
    };

    view! {
        <div class="power-btn-wrap" on:click=move |ev| ev.stop_propagation()>
            // ── trigger button ───────────────────────────────────────────
            <button
                class=move || {
                    let base = "power-btn";
                    match state.get() {
                        ButtonState::Idle | ButtonState::Done(_) => base.to_string(),
                        _ => format!("{} power-btn-active", base),
                    }
                }
                title=move || t_string!(i18n, common::power_controls)
                on:click=on_power_click
                disabled=move || matches!(state.get(), ButtonState::Executing)
            >
                // Power icon (SVG)
                <svg
                    class="power-btn-icon"
                    viewBox="0 0 24 24"
                    fill="none"
                    xmlns="http://www.w3.org/2000/svg"
                >
                    <path
                        d="M12 3v9"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                    />
                    <path
                        d="M7.07 5.93A9 9 0 1 0 16.93 5.93"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                    />
                </svg>
            </button>

            // ── dropdown menu ────────────────────────────────────────────
            {move || {
                if state.get() != ButtonState::Menu {
                    return view! { <></> }.into_any();
                }
                view! {
                    <div class="power-dropdown">
                        <button
                            class="power-dropdown-item"
                            on:click=on_action_click(PowerAction::Restart)
                        >
                            // Restart icon
                            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none">
                                <path
                                    d="M1 4v6h6"
                                    stroke="currentColor"
                                    stroke-width="2"
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                />
                                <path
                                    d="M3.51 15a9 9 0 1 0 .49-3.51L1 10"
                                    stroke="currentColor"
                                    stroke-width="2"
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                />
                            </svg>
                            {t_string!(i18n, common::restart)}
                        </button>
                        <button
                            class="power-dropdown-item power-dropdown-item-danger"
                            on:click=on_action_click(PowerAction::Shutdown)
                        >
                            // Power-off icon
                            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none">
                                <path
                                    d="M12 3v9"
                                    stroke="currentColor"
                                    stroke-width="2"
                                    stroke-linecap="round"
                                />
                                <path
                                    d="M7.07 5.93A9 9 0 1 0 16.93 5.93"
                                    stroke="currentColor"
                                    stroke-width="2"
                                    stroke-linecap="round"
                                />
                            </svg>
                            {t_string!(i18n, common::shutdown)}
                        </button>
                    </div>
                }
                .into_any()
            }}

            // ── confirmation panel ───────────────────────────────────────
            {move || {
                let action = match state.get() {
                    ButtonState::Confirm(a) => a,
                    _ => return view! { <></> }.into_any(),
                };
                view! {
                    <div class="power-dropdown power-confirm">
                        <p class="power-confirm-msg">
                            {action.confirm_msg(i18n)}
                        </p>
                        <div class="power-confirm-actions">
                            <button
                                class="power-confirm-btn power-confirm-btn-cancel"
                                on:click=on_cancel_click
                            >
                                {t_string!(i18n, common::cancel)}
                            </button>
                            <button
                                class="power-confirm-btn power-confirm-btn-ok"
                                on:click=on_confirm_click
                            >
                                {action.label(i18n)}
                            </button>
                        </div>
                    </div>
                }
                .into_any()
            }}

            // ── executing spinner ────────────────────────────────────────
            {move || {
                if state.get() != ButtonState::Executing {
                    return view! { <></> }.into_any();
                }
                view! {
                    <div class="power-dropdown power-executing">
                        <span class="power-spinner"></span>
                        {t_string!(i18n, common::sending_command)}
                    </div>
                }
                .into_any()
            }}

            // ── result badge (fades away) ────────────────────────────────
            {move || {
                let ok = match state.get() {
                    ButtonState::Done(v) => v,
                    _ => return view! { <></> }.into_any(),
                };
                view! {
                    <div class=move || {
                        if ok {
                            "power-dropdown power-result power-result-ok"
                        } else {
                            "power-dropdown power-result power-result-err"
                        }
                    }>
                        {if ok {
                            t_string!(i18n, common::command_sent)
                        } else {
                            t_string!(i18n, common::command_failed)
                        }}
                    </div>
                }
                .into_any()
            }}
        </div>
    }
}
