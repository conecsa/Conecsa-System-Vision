//! Leptos UI components for the web frontend.

use crate::app::ModelInfo;
use crate::i18n::*;
use leptos::prelude::*;

mod model_row;

use model_row::ModelRow;

#[component]
pub(super) fn ModelList(
    models: ReadSignal<Vec<ModelInfo>>,
    on_select: Callback<String>,
    set_context_menu_x: WriteSignal<i32>,
    set_context_menu_y: WriteSignal<i32>,
    set_selected_model_for_delete: WriteSignal<String>,
    set_context_menu_visible: WriteSignal<bool>,
    set_error_msg: WriteSignal<String>,
) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        {move || {
            let model_list = models.get();
            let should_scroll = model_list.len() >= 3;
            if model_list.is_empty() {
                view! {
                    <div class="h-full flex items-center justify-center">
                        <p class="ui-empty">{t!(i18n, models::no_models_loaded)}</p>
                    </div>
                }.into_any()
            } else {
                view! {
                    <div class={if should_scroll {
                        "flex flex-col gap-2 max-h-[220px] overflow-y-auto pr-1"
                    } else {
                        "flex flex-col gap-2"
                    }}>
                        {model_list.into_iter().map(|model| {
                            view! {
                                <ModelRow
                                    model=model
                                    on_select=on_select
                                    set_context_menu_x=set_context_menu_x
                                    set_context_menu_y=set_context_menu_y
                                    set_selected_model_for_delete=set_selected_model_for_delete
                                    set_context_menu_visible=set_context_menu_visible
                                    set_error_msg=set_error_msg
                                />
                            }
                        }).collect_view()}
                    </div>
                }.into_any()
            }
        }}
    }
}
