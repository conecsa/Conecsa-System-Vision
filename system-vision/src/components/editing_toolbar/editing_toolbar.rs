//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

use super::toolbar_icon::ToolbarIcon;

/// Floating control bar shown at the bottom of the live stream while a
/// detection area is in editing mode. All actions are emitted as callbacks;
/// the parent owns the API calls and the area state.
#[component]
pub fn EditingToolbar(
    /// Reactive read of the currently editing area's shape ("rectangle" or
    /// "circle"). Drives the icon shown on the toggle button.
    editing_shape: Signal<String>,
    /// Semantic motion / sizing actions:
    /// `move_up`, `move_down`, `move_left`, `move_right`,
    /// `grow`, `shrink`, `grow_horizontal`, `shrink_horizontal`,
    /// `grow_vertical`, `shrink_vertical`.
    on_command: Callback<&'static str>,
    on_toggle_shape: Callback<()>,
    on_save: Callback<()>,
    /// Exits editing mode without committing further changes (and without
    /// deleting the area - use the chip's delete button to delete).
    on_cancel: Callback<()>,
) -> impl IntoView {
    let i18n = use_i18n();
    view! {
        <div class="ui-tool-panel absolute bottom-2 left-1/2 -translate-x-1/2 flex flex-wrap items-center justify-center gap-1 px-3 py-2 max-w-[95%]">
            // Movement
            <button class="ui-tool-button w-8 h-8" title=move || t_string!(i18n, stream::move_up) on:click=move |_| on_command.run("move_up")>
                <ToolbarIcon>
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19V5m0 0l-6 6m6-6l6 6" />
                </ToolbarIcon>
            </button>
            <button class="ui-tool-button w-8 h-8" title=move || t_string!(i18n, stream::move_down) on:click=move |_| on_command.run("move_down")>
                <ToolbarIcon>
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 5v14m0 0l-6-6m6 6l6-6" />
                </ToolbarIcon>
            </button>
            <button class="ui-tool-button w-8 h-8" title=move || t_string!(i18n, stream::move_left) on:click=move |_| on_command.run("move_left")>
                <ToolbarIcon>
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 12H5m0 0l6-6m-6 6l6 6" />
                </ToolbarIcon>
            </button>
            <button class="ui-tool-button w-8 h-8" title=move || t_string!(i18n, stream::move_right) on:click=move |_| on_command.run("move_right")>
                <ToolbarIcon>
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14m0 0l-6-6m6 6l-6 6" />
                </ToolbarIcon>
            </button>
            <span class="ui-tool-divider">"|"</span>
            // Width
            <button class="ui-tool-button w-10 h-8" title=move || t_string!(i18n, stream::increase_width) on:click=move |_| on_command.run("grow_horizontal")>
                <ToolbarIcon>
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12h18M7 8l-4 4 4 4M17 8l4 4-4 4" />
                </ToolbarIcon>
            </button>
            <button class="ui-tool-button w-10 h-8" title=move || t_string!(i18n, stream::decrease_width) on:click=move |_| on_command.run("shrink_horizontal")>
                <ToolbarIcon>
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12h7m0 0L6 8m4 4l-4 4M21 12h-7m0 0l4-4m-4 4l4 4" />
                </ToolbarIcon>
            </button>
            // Height
            <button class="ui-tool-button w-10 h-8" title=move || t_string!(i18n, stream::increase_height) on:click=move |_| on_command.run("grow_vertical")>
                <ToolbarIcon>
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v18M8 7l4-4 4 4M8 17l4 4 4-4" />
                </ToolbarIcon>
            </button>
            <button class="ui-tool-button w-10 h-8" title=move || t_string!(i18n, stream::decrease_height) on:click=move |_| on_command.run("shrink_vertical")>
                <ToolbarIcon>
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v7m0 0L8 6m4 4l4-4M12 21v-7m0 0l-4 4m4-4l4 4" />
                </ToolbarIcon>
            </button>
            // Uniform
            <span class="ui-tool-divider">"|"</span>
            <button class="ui-tool-button w-8 h-8" title=move || t_string!(i18n, stream::grow) on:click=move |_| on_command.run("grow")>
                <ToolbarIcon>
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 3H3v5M3 3l7 7M16 3h5v5M21 3l-7 7M8 21H3v-5M3 21l7-7M16 21h5v-5M21 21l-7-7" />
                </ToolbarIcon>
            </button>
            <button class="ui-tool-button w-8 h-8" title=move || t_string!(i18n, stream::shrink) on:click=move |_| on_command.run("shrink")>
                <ToolbarIcon>
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4l6 6M10 4v6H4M20 4l-6 6M14 4v6h6M4 20l6-6M10 20v-6H4M20 20l-6-6M14 20v-6h6" />
                </ToolbarIcon>
            </button>
            // Shape toggle
            <span class="ui-tool-divider">"|"</span>
            <button class="ui-tool-button w-8 h-8" title=move || t_string!(i18n, stream::toggle_shape) on:click=move |_| on_toggle_shape.run(())>
                {move || {
                    if editing_shape.get() == "circle" {
                        view! {
                            <ToolbarIcon>
                                <circle cx="12" cy="12" r="6" stroke-width="2" />
                            </ToolbarIcon>
                        }
                            .into_any()
                    } else {
                        view! {
                            <ToolbarIcon>
                                <rect x="6" y="6" width="12" height="12" rx="1.5" stroke-width="2" />
                            </ToolbarIcon>
                        }
                            .into_any()
                    }
                }}
            </button>
            // Commit / cancel
            <span class="ui-tool-divider">"|"</span>
            <button class="ui-tool-button ui-tool-button-success w-8 h-8" title=move || t_string!(i18n, common::save) on:click=move |_| on_save.run(())>
                <ToolbarIcon>
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                </ToolbarIcon>
            </button>
            <button class="ui-tool-button ui-tool-button-danger w-8 h-8" title=move || t_string!(i18n, common::cancel) on:click=move |_| on_cancel.run(())>
                <ToolbarIcon>
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </ToolbarIcon>
            </button>
        </div>
    }
}
