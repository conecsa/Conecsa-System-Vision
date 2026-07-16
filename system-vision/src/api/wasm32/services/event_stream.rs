//! Application event stream consumer.
//!
//! Opens `/api/v1/events/stream?stats=1` and forwards each event to the
//! caller. Most events are lightweight invalidations (components should
//! re-fetch their canonical state when a relevant key changes); `type:
//! "stats"` events carry the live performance stats payload under `data`,
//! multiplexed onto the same connection so the UI needs only one stream.

use leptos::logging;
use serde::Deserialize;
use serde_json::Value;
use wasm_bindgen::prelude::*;
use wasm_bindgen::JsCast;
use web_sys::{EventSource, MessageEvent};

use crate::app::get_api_base_url;

/// An `AppEvent` struct.
#[derive(Debug, Clone, Deserialize)]
pub struct AppEvent {
    pub version: u64,
    #[serde(rename = "type")]
    pub event_type: String,
    pub source: String,
    #[serde(default)]
    pub keys: Vec<String>,
    #[serde(default)]
    pub data: Value,
}

/// An `AppEventStreamHandle` struct.
pub struct AppEventStreamHandle {
    es: EventSource,
    _on_message: Closure<dyn FnMut(MessageEvent)>,
    _on_error: Closure<dyn FnMut(JsValue)>,
}

impl Drop for AppEventStreamHandle {
    /// Drop.
    fn drop(&mut self) {
        self.es.close();
    }
}

/// Subscribe app events.
pub fn subscribe_app_events<F>(on_event: F) -> Result<AppEventStreamHandle, String>
where
    F: Fn(AppEvent) + 'static,
{
    // ?stats=1 opts this connection into the multiplexed high-rate stats
    // channel, so the web UI needs a single SSE connection (events + stats).
    let url = format!("{}/api/v1/events/stream?stats=1", get_api_base_url());
    let es = EventSource::new(&url).map_err(|e| format!("Failed to open EventSource: {:?}", e))?;

    let on_message = Closure::wrap(Box::new(move |evt: MessageEvent| {
        let Some(data) = evt.data().as_string() else {
            logging::error!("App event data is not a string");
            return;
        };
        match serde_json::from_str::<AppEvent>(&data) {
            Ok(event) => on_event(event),
            Err(e) => logging::error!("Failed to parse app event: {}", e),
        }
    }) as Box<dyn FnMut(MessageEvent)>);
    es.set_onmessage(Some(on_message.as_ref().unchecked_ref()));

    let on_error = Closure::wrap(Box::new(move |_evt: JsValue| {
        logging::warn!("App event SSE error; browser will auto-reconnect");
    }) as Box<dyn FnMut(JsValue)>);
    es.set_onerror(Some(on_error.as_ref().unchecked_ref()));

    Ok(AppEventStreamHandle {
        es,
        _on_message: on_message,
        _on_error: on_error,
    })
}
