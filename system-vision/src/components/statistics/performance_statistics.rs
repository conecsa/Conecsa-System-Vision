//! Leptos UI components for the web frontend.

use super::stat_card::StatCard;
use crate::components::panel_header::PanelHeader;
use crate::i18n::*;
use crate::models::PerformanceStats;
use leptos::prelude::*;

/// The `PerformanceStatistics` view component.
#[component]
pub fn PerformanceStatistics(stats: ReadSignal<Option<PerformanceStats>>) -> impl IntoView {
    let i18n = use_i18n();

    let fps = Signal::derive(move || {
        stats
            .get()
            .map(|s| format!("{:.1}", s.fps))
            .unwrap_or("0.0".to_string())
    });
    let inference_time = Signal::derive(move || {
        stats
            .get()
            .map(|s| format!("{:.1}ms", s.inference_time))
            .unwrap_or("0.0ms".to_string())
    });
    let detections = Signal::derive(move || {
        stats
            .get()
            .map(|s| s.detections.to_string())
            .unwrap_or("0".to_string())
    });
    let frames_with_detections = Signal::derive(move || {
        stats
            .get()
            .map(|s| s.frames_with_detections.to_string())
            .unwrap_or("0".to_string())
    });

    view! {
        <div class="ui-card ui-card-pad h-full overflow-hidden flex flex-col">
            <PanelHeader title=move || t_string!(i18n, statistics::title)>
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </PanelHeader>
            <div class="flex-1 min-h-0 overflow-y-auto grid grid-cols-2 grid-rows-[repeat(2,minmax(7rem,1fr))] gap-3">
                <StatCard label="FPS" value=fps>
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                </StatCard>
                <StatCard
                    label=move || t_string!(i18n, statistics::inference_time)
                    value=inference_time
                >
                    <circle cx="12" cy="12" r="10" stroke-width="2"/>
                    <polyline points="12 6 12 12 16 14" stroke-width="2"/>
                </StatCard>
                <StatCard
                    label=move || t_string!(i18n, statistics::detections)
                    value=detections
                >
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                </StatCard>
                <StatCard
                    label=move || t_string!(i18n, statistics::frames_with_detections)
                    value=frames_with_detections
                >
                    <rect x="2" y="3" width="20" height="14" rx="2" stroke-width="2"/>
                    <line x1="8" y1="21" x2="16" y2="21" stroke-width="2"/>
                    <line x1="12" y1="17" x2="12" y2="21" stroke-width="2"/>
                </StatCard>
            </div>
        </div>
    }
}
