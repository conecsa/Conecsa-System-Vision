//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn StereoOverlayToggle(
    stereo_supported: Signal<bool>,
    selected_stereo_enabled: ReadSignal<bool>,
    set_selected_stereo_enabled: WriteSignal<bool>,
    on_push: Callback<bool>,
) -> impl IntoView {
    let i18n = use_i18n();

    view! {
        {move || if !stereo_supported.get() {
            view! { <></> }.into_any()
        } else {
            view! {
                <div class="flex flex-col gap-2">
                    <div class="flex items-center justify-between">
                        <label class="ui-label">
                            {t_string!(i18n, camera::stereo_overlay)}
                        </label>
                        <button
                            type="button"
                            class={move || {
                                if selected_stereo_enabled.get() {
                                    "ui-toggle ui-toggle-on cursor-pointer"
                                } else {
                                    "ui-toggle ui-toggle-off cursor-pointer"
                                }
                            }}
                            on:click=move |_| {
                                let v = !selected_stereo_enabled.get();
                                set_selected_stereo_enabled.set(v);
                                on_push.run(v);
                            }
                        >
                            <span class={move || {
                                if selected_stereo_enabled.get() {
                                    "ui-toggle-knob ui-toggle-knob-on"
                                } else {
                                    "ui-toggle-knob"
                                }
                            }}></span>
                        </button>
                    </div>

                    <p class="ui-help">
                        {t_string!(i18n, camera::stereo_overlay_help)}
                    </p>
                </div>
            }.into_any()
        }}
    }
}
