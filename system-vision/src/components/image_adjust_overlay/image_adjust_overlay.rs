//! Image-adjustment control: a button over the live video that reveals a panel
//! with Exposure / RGB / Gamma / Gain. Self-fetches its state from the camera
//! config and applies each change live (none of these trigger a camera restart).
use leptos::prelude::*;
use leptos::task::spawn_local;

use crate::api;

use super::panel::ImageAdjustmentPanel;
use super::toggle_button::ImageAdjustmentToggleButton;

/// Each helper sends only the relevant field(s) so changes apply live.
fn push_exposure(auto: bool, time: u32) {
    spawn_local(async move {
        let _ = api::update_camera_config(
            None,
            None,
            None,
            None,
            Some(auto),
            Some(time),
            None,
            None,
            None,
            None,
            None,
        )
        .await;
    });
}

/// Push rgb.
fn push_rgb(r: u16, g: u16, b: u16) {
    spawn_local(async move {
        let _ = api::update_camera_config(
            None,
            None,
            None,
            None,
            None,
            None,
            Some(r),
            Some(g),
            Some(b),
            None,
            None,
        )
        .await;
    });
}

/// Push gamma.
fn push_gamma(gamma: u32) {
    spawn_local(async move {
        let _ = api::update_camera_config(
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            Some(gamma),
            None,
        )
        .await;
    });
}

/// Push gain.
fn push_gain(gain: u32) {
    spawn_local(async move {
        let _ = api::update_camera_config(
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            Some(gain),
        )
        .await;
    });
}

/// The `ImageAdjustOverlay` view component.
#[component]
pub fn ImageAdjustOverlay(
    /// Bumped on model select; camera image settings are per-model, so re-fetch.
    model_refresh: ReadSignal<u32>,
    /// Bumped when any client changes camera settings.
    camera_refresh: ReadSignal<u32>,
    /// Shared open-panel id across the stream overlays (mutual exclusion).
    panel: RwSignal<u8>,
) -> impl IntoView {
    let (auto_exposure, set_auto_exposure) = signal(false);
    let (exposure_time, set_exposure_time) = signal(333u32);
    let (exp_min, set_exp_min) = signal(1u32);
    let (exp_max, set_exp_max) = signal(300_000u32);
    let (rgb_red, set_rgb_red) = signal(128u16);
    let (rgb_green, set_rgb_green) = signal(128u16);
    let (rgb_blue, set_rgb_blue) = signal(128u16);
    let (gamma, set_gamma) = signal(100u32);
    let (gain, set_gain) = signal(0u32);

    // Fetch state on mount and on model change.
    Effect::new(move |_| {
        let _ = model_refresh.get();
        let _ = camera_refresh.get();
        spawn_local(async move {
            if let Ok(resp) = api::get_camera_devices().await {
                set_auto_exposure.set(resp.current_auto_exposure);
                set_exposure_time.set(resp.current_exposure_time);
                set_exp_min.set(resp.exposure_time_min);
                set_exp_max.set(resp.exposure_time_max);
                set_rgb_red.set(resp.current_rgb_red);
                set_rgb_green.set(resp.current_rgb_green);
                set_rgb_blue.set(resp.current_rgb_blue);
                set_gamma.set(resp.current_gamma);
                set_gain.set(resp.current_gain);
            }
        });
    });

    let on_push_exposure =
        Callback::new(move |(auto, time): (bool, u32)| push_exposure(auto, time));
    let on_push_rgb = Callback::new(move |(r, g, b): (u16, u16, u16)| push_rgb(r, g, b));
    let on_push_gamma = Callback::new(move |value: u32| push_gamma(value));
    let on_push_gain = Callback::new(move |value: u32| push_gain(value));

    view! {
        <ImageAdjustmentToggleButton panel=panel />
        <ImageAdjustmentPanel
            panel=panel
            auto_exposure=auto_exposure
            set_auto_exposure=set_auto_exposure
            exposure_time=exposure_time
            set_exposure_time=set_exposure_time
            exp_min=exp_min
            exp_max=exp_max
            rgb_red=rgb_red
            set_rgb_red=set_rgb_red
            rgb_green=rgb_green
            set_rgb_green=set_rgb_green
            rgb_blue=rgb_blue
            set_rgb_blue=set_rgb_blue
            gamma=gamma
            set_gamma=set_gamma
            gain=gain
            set_gain=set_gain
            on_push_exposure=on_push_exposure
            on_push_rgb=on_push_rgb
            on_push_gamma=on_push_gamma
            on_push_gain=on_push_gain
        />
    }
}
