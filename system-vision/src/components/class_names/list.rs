//! Leptos UI components for the web frontend.

use super::class_badge::ClassBadge;
use crate::class_color::class_color_for;
use crate::i18n::*;
use leptos::prelude::*;

#[component]
pub(super) fn ClassList(classes: ReadSignal<Vec<String>>) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        <div class="ui-list-box p-3 h-[100px] overflow-y-auto">
            {move || {
                let class_list = classes.get();
                if class_list.is_empty() {
                    view! {
                        <p class="ui-empty py-4">{t!(i18n, models::no_classes_configured)}</p>
                    }.into_any()
                } else {
                    view! {
                        <div class="flex flex-wrap gap-2">
                            {class_list.iter().enumerate().map(|(idx, class_entry)| {
                                view! {
                                    <ClassBadge
                                        index=idx
                                        class_entry=class_entry.clone()
                                        color=class_color_for(idx, &class_list)
                                    />
                                }
                            }).collect_view()}
                        </div>
                    }.into_any()
                }
            }}
        </div>
    }
}
