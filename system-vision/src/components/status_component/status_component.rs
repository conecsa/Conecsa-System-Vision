//! Leptos UI components for the web frontend.

use crate::api::get_system_metrics;
use crate::i18n::*;
use leptos::prelude::*;
use leptos::task::spawn_local;

use super::metrics_grid::SystemMetricsGrid;
use super::SystemMetrics;

/// The `StatusComponent` view component.
#[component]
pub fn StatusComponent() -> impl IntoView {
    let i18n = use_i18n();
    let (status, set_status) = signal(SystemMetrics::default());
    let (is_loading, set_is_loading) = signal(true);

    // Update system status every 2 seconds
    Effect::new(move |_| {
        let update_status = move || {
            spawn_local(async move {
                match get_system_metrics().await {
                    Ok(new_status) => {
                        set_status.set(new_status);
                        set_is_loading.set(false);
                    }
                    Err(e) => {
                        leptos::logging::error!("Error fetching system status: {}", e);
                        set_is_loading.set(false);
                    }
                }
            });
        };

        // Initial fetch
        update_status();

        // Set up interval for subsequent fetches
        let interval = gloo_timers::callback::Interval::new(2000, move || {
            update_status();
        });

        // Keep interval alive by forgetting it
        interval.forget();
    });

    view! {
        <div class="ui-card ui-card-pad-sm">
            <h2 class="ui-section-header ui-section-header-lg">
                <svg class="w-5 h-5 stroke-current ui-icon-muted" viewBox="0 0 24 24" fill="none">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z" />
                </svg>
                {t!(i18n, main::system_status)}
            </h2>

            {move || {
                if is_loading.get() {
                    view! {
                        <div class="flex items-center justify-center py-4">
                            <div class="ui-spinner h-8 w-8"></div>
                        </div>
                    }
                        .into_any()
                } else {
                    view! {
                        <SystemMetricsGrid status=status />
                    }
                        .into_any()
                }
            }}
        </div>
    }
}
