//! The "3D" toggle button that shows/hides the stereo overlay alignment panel.

use super::PANEL_ID;
use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn StereoToggleButton(enabled: ReadSignal<bool>, panel: RwSignal<u8>) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        {move || if enabled.get() {
            view! {
                <div class="absolute top-2 right-26">
                    <button
                        type="button"
                        class=move || {
                            if panel.get() == PANEL_ID {
                                "ui-overlay-toggle ui-overlay-toggle-active text-sm font-bold"
                            } else {
                                "ui-overlay-toggle text-sm font-bold"
                            }
                        }
                        title=t_string!(i18n, stream::stereo_toggle_tooltip)
                        on:click=move |_| panel.update(|p| *p = if *p == PANEL_ID { 0 } else { PANEL_ID })
                    >
                        "3D"
                    </button>
                </div>
            }.into_any()
        } else {
            view! { <></> }.into_any()
        }}
    }
}
