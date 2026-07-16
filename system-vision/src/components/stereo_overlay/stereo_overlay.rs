//! 3D stereo overlay alignment control: a button over the live video (shown
//! only when the stereo overlay is enabled in Camera Settings) that reveals a
//! Blend / Horizontal / Vertical alignment panel. Self-fetches its state from
//! the camera config and applies changes live (no camera restart).
use leptos::prelude::*;
use leptos::task::spawn_local;

use crate::api;

use super::alignment_panel::StereoAlignmentPanel;
use super::toggle_button::StereoToggleButton;

/// Push the stereo combine alignment settings. Applied immediately by the
/// inference-service (no camera restart).
fn push_stereo(alpha: f32, offset: f32, offset_y: f32) {
    spawn_local(async move {
        let _ = api::update_stereo_config(None, Some(alpha), Some(offset), Some(offset_y)).await;
    });
}

/// The `StereoOverlay` view component.
#[component]
pub fn StereoOverlay(
    /// Bumped on model select; stereo settings are per-model, so re-fetch.
    model_refresh: ReadSignal<u32>,
    /// Bumped when any client changes camera/stereo settings.
    camera_refresh: ReadSignal<u32>,
    /// Shared open-panel id across the stream overlays (mutual exclusion).
    panel: RwSignal<u8>,
) -> impl IntoView {
    let (enabled, set_enabled) = signal(false);
    let (alpha, set_alpha) = signal(0.5f32);
    let (offset_x, set_offset_x) = signal(0.0f32);
    let (offset_y, set_offset_y) = signal(0.0f32);

    // Fetch state on mount and on model change.
    Effect::new(move |_| {
        let _ = model_refresh.get();
        let _ = camera_refresh.get();
        spawn_local(async move {
            if let Ok(resp) = api::get_camera_devices().await {
                set_enabled.set(resp.current_stereo_enabled);
                set_alpha.set(resp.current_stereo_blend_alpha);
                set_offset_x.set(resp.current_stereo_offset);
                set_offset_y.set(resp.current_stereo_offset_y);
            }
        });
    });

    let on_push = Callback::new(move |(a, x, y): (f32, f32, f32)| push_stereo(a, x, y));

    view! {
        <StereoToggleButton enabled=enabled panel=panel />
        <StereoAlignmentPanel
            enabled=enabled
            panel=panel
            alpha=alpha
            set_alpha=set_alpha
            offset_x=offset_x
            set_offset_x=set_offset_x
            offset_y=offset_y
            set_offset_y=set_offset_y
            on_push=on_push
        />
    }
}
