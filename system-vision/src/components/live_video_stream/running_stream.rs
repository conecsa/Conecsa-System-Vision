//! Leptos UI components for the web frontend.

use crate::app::get_api_base_url;
use crate::components::add_area_button::AddAreaButton;
use crate::components::area_chips::{AreaChips, AreaView};
use crate::components::editing_toolbar::EditingToolbar;
use crate::components::image_adjust_overlay::ImageAdjustOverlay;
use crate::components::stereo_overlay::StereoOverlay;
use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn RunningStream(
    reload_key: ReadSignal<u32>,
    set_reload_key: WriteSignal<u32>,
    areas: ReadSignal<Vec<AreaView>>,
    panel: RwSignal<u8>,
    model_refresh: ReadSignal<u32>,
    camera_refresh: ReadSignal<u32>,
    editing_id: Signal<Option<String>>,
    editing_shape: Signal<String>,
    on_add: Callback<()>,
    on_edit_chip: Callback<String>,
    on_delete_chip: Callback<String>,
    on_command: Callback<&'static str>,
    on_toggle_shape: Callback<()>,
    on_save: Callback<()>,
    on_cancel: Callback<()>,
) -> impl IntoView {
    let i18n = use_i18n();
    let base_url = get_api_base_url();
    let video_url = move || {
        format!(
            "{}/api/v1/video_feed_processed?r={}",
            base_url,
            reload_key.get()
        )
    };

    view! {
        <div class="stream-stage relative w-full h-full flex items-center justify-center overflow-hidden">
            <img
                src=video_url
                class="max-w-full max-h-full object-contain rounded"
                alt=move || t_string!(i18n, stream::live_video_stream)
                on:error=move |_| {
                    set_timeout(
                        move || set_reload_key.update(|k| *k += 1),
                        std::time::Duration::from_millis(1000),
                    );
                }
            />

            <AreaChips areas=areas on_edit=on_edit_chip on_delete=on_delete_chip />
            <AddAreaButton on_add=on_add />

            <ImageAdjustOverlay
                model_refresh=model_refresh
                camera_refresh=camera_refresh
                panel=panel
            />
            <StereoOverlay
                model_refresh=model_refresh
                camera_refresh=camera_refresh
                panel=panel
            />

            {move || {
                if editing_id.get().is_some() {
                    view! {
                        <EditingToolbar
                            editing_shape=editing_shape
                            on_command=on_command
                            on_toggle_shape=on_toggle_shape
                            on_save=on_save
                            on_cancel=on_cancel
                        />
                    }.into_any()
                } else {
                    view! { <></> }.into_any()
                }
            }}
        </div>
    }
}
