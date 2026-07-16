//! Leptos UI components for the web frontend.

use crate::i18n::*;
use leptos::prelude::*;

mod pin_cell;

use pin_cell::{PinCell, PinKind};

/// Complete Jetson Orin Nano 40-pin header (BOARD numbering). Pin 7 is the
/// trigger input; pins 29/31/33 are the controllable digital
/// outputs (driven from Node-RED). The rest are reference-only.
/// Verify against the device `Jetson.GPIO` pin data / `jetson-io` if in doubt.
const PINS: [(u8, &str, PinKind); 40] = [
    (1, "3.3V", PinKind::Power),
    (2, "5V", PinKind::Power),
    (3, "I2C1_SDA", PinKind::Other),
    (4, "5V", PinKind::Power),
    (5, "I2C1_SCL", PinKind::Other),
    (6, "GND", PinKind::Ground),
    (7, "GPIO09 (Trigger IN)", PinKind::Trigger),
    (8, "UART1_TXD", PinKind::Other),
    (9, "GND", PinKind::Ground),
    (10, "UART1_RXD", PinKind::Other),
    (11, "UART1_RTS", PinKind::Other),
    (12, "I2S0_SCLK", PinKind::Other),
    (13, "SPI1_SCK", PinKind::Other),
    (14, "GND", PinKind::Ground),
    (15, "GPIO12 (PWM)", PinKind::Other),
    (16, "SPI1_CS1", PinKind::Other),
    (17, "3.3V", PinKind::Power),
    (18, "SPI1_CS0", PinKind::Other),
    (19, "SPI0_MOSI", PinKind::Other),
    (20, "GND", PinKind::Ground),
    (21, "SPI0_MISO", PinKind::Other),
    (22, "SPI1_MISO", PinKind::Other),
    (23, "SPI0_SCK", PinKind::Other),
    (24, "SPI0_CS0", PinKind::Other),
    (25, "GND", PinKind::Ground),
    (26, "SPI0_CS1", PinKind::Other),
    (27, "I2C0_SDA", PinKind::Other),
    (28, "I2C0_SCL", PinKind::Other),
    (29, "GPIO01 (Output)", PinKind::Output),
    (30, "GND", PinKind::Ground),
    (31, "GPIO11 (Output)", PinKind::Output),
    (32, "GPIO07 (PWM)", PinKind::Other),
    (33, "GPIO13 (Output)", PinKind::Output),
    (34, "GND", PinKind::Ground),
    (35, "I2S0_FS", PinKind::Other),
    (36, "UART1_CTS", PinKind::Other),
    (37, "SPI1_MOSI", PinKind::Other),
    (38, "I2S0_SDIN", PinKind::Other),
    (39, "GND", PinKind::Ground),
    (40, "I2S0_SDOUT", PinKind::Other),
];

#[component]
pub(super) fn PinMap() -> impl IntoView {
    let i18n = use_i18n();
    // Render in physical-header order: odd pins (left) paired with even (right).
    let rows = (0..PINS.len() / 2).map(|i| {
        let (lp, ln, lk) = PINS[i * 2];
        let (rp, rn, rk) = PINS[i * 2 + 1];
        view! {
            <PinCell pin=lp name=ln kind=lk flip=false />
            <PinCell pin=rp name=rn kind=rk flip=true />
        }
    }).collect_view();

    view! {
        <div class="mt-2">
            <h3 class="ui-section-title mb-2">
                {t!(i18n, settings::pin_map_title)}
            </h3>
            <div class="max-h-72 overflow-y-auto pr-1">
                <div class="grid grid-cols-2 gap-2 text-xs">
                    {rows}
                </div>
            </div>
            <p class="ui-help mt-2">
                {t!(i18n, settings::pin_map_help)}
            </p>
        </div>
    }
}
