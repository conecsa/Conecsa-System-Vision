//! Leptos UI components for the web frontend.

use super::exposure_control::ExposureControl;
use super::range_control::RangeControl;
use super::rgb_control::RgbControl;
use super::PANEL_ID;
use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn ImageAdjustmentPanel(
    panel: RwSignal<u8>,
    auto_exposure: ReadSignal<bool>,
    set_auto_exposure: WriteSignal<bool>,
    exposure_time: ReadSignal<u32>,
    set_exposure_time: WriteSignal<u32>,
    exp_min: ReadSignal<u32>,
    exp_max: ReadSignal<u32>,
    rgb_red: ReadSignal<u16>,
    set_rgb_red: WriteSignal<u16>,
    rgb_green: ReadSignal<u16>,
    set_rgb_green: WriteSignal<u16>,
    rgb_blue: ReadSignal<u16>,
    set_rgb_blue: WriteSignal<u16>,
    gamma: ReadSignal<u32>,
    set_gamma: WriteSignal<u32>,
    gain: ReadSignal<u32>,
    set_gain: WriteSignal<u32>,
    on_push_exposure: Callback<(bool, u32)>,
    on_push_rgb: Callback<(u16, u16, u16)>,
    on_push_gamma: Callback<u32>,
    on_push_gain: Callback<u32>,
) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        {move || if panel.get() == PANEL_ID {
            view! {
                <div class="ui-tool-panel stream-drawer w-72 p-3 flex flex-col gap-3">
                    <div class="text-xs font-semibold">{t!(i18n, stream::image_adjustments)}</div>
                    <ExposureControl
                        auto_exposure=auto_exposure
                        set_auto_exposure=set_auto_exposure
                        exposure_time=exposure_time
                        set_exposure_time=set_exposure_time
                        exp_min=exp_min
                        exp_max=exp_max
                        on_push_exposure=on_push_exposure
                    />
                    <RgbControl
                        rgb_red=rgb_red
                        set_rgb_red=set_rgb_red
                        rgb_green=rgb_green
                        set_rgb_green=set_rgb_green
                        rgb_blue=rgb_blue
                        set_rgb_blue=set_rgb_blue
                        on_push_rgb=on_push_rgb
                    />
                    <RangeControl
                        label=move || t_string!(i18n, stream::gamma)
                        min=1
                        max=500
                        value=gamma
                        set_value=set_gamma
                        on_push=on_push_gamma
                    />
                    <RangeControl
                        label=move || t_string!(i18n, stream::gain)
                        min=0
                        max=480
                        value=gain
                        set_value=set_gain
                        on_push=on_push_gain
                    />
                </div>
            }.into_any()
        } else {
            view! { <></> }.into_any()
        }}
    }
}
