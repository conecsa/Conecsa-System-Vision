//! The stereo overlay alignment panel (blend + horizontal/vertical offset).

use super::range_control::StereoRangeControl;
use super::PANEL_ID;
use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn StereoAlignmentPanel(
    enabled: ReadSignal<bool>,
    panel: RwSignal<u8>,
    alpha: ReadSignal<f32>,
    set_alpha: WriteSignal<f32>,
    offset_x: ReadSignal<f32>,
    set_offset_x: WriteSignal<f32>,
    offset_y: ReadSignal<f32>,
    set_offset_y: WriteSignal<f32>,
    on_push: Callback<(f32, f32, f32)>,
) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        {move || if enabled.get() && panel.get() == PANEL_ID {
            view! {
                <div class="ui-tool-panel stream-drawer w-64 p-3 flex flex-col gap-2">
                    <div class="text-xs font-semibold">{t!(i18n, stream::stereo_alignment_title)}</div>
                    <StereoRangeControl
                        label=move || t_string!(i18n, stream::blend)
                        value=Signal::derive(move || alpha.get() * 100.0)
                        display=Signal::derive(move || format!("{:.0}%", alpha.get() * 100.0))
                        min=0
                        max=100
                        on_change=Callback::new(move |p: f32| {
                            let a = (p / 100.0).clamp(0.0, 1.0);
                            set_alpha.set(a);
                            on_push.run((a, offset_x.get(), offset_y.get()));
                        })
                    />
                    <StereoRangeControl
                        label=move || t_string!(i18n, stream::horizontal)
                        value=Signal::derive(move || offset_x.get() * 100.0)
                        display=Signal::derive(move || format!("{:+.0}%", offset_x.get() * 100.0))
                        min=-50
                        max=50
                        on_change=Callback::new(move |p: f32| {
                            let o = (p / 100.0).clamp(-0.5, 0.5);
                            set_offset_x.set(o);
                            on_push.run((alpha.get(), o, offset_y.get()));
                        })
                    />
                    <StereoRangeControl
                        label=move || t_string!(i18n, stream::vertical)
                        value=Signal::derive(move || offset_y.get() * 100.0)
                        display=Signal::derive(move || format!("{:+.0}%", offset_y.get() * 100.0))
                        min=-50
                        max=50
                        on_change=Callback::new(move |p: f32| {
                            let o = (p / 100.0).clamp(-0.5, 0.5);
                            set_offset_y.set(o);
                            on_push.run((alpha.get(), offset_x.get(), o));
                        })
                    />
                </div>
            }.into_any()
        } else {
            view! { <></> }.into_any()
        }}
    }
}
