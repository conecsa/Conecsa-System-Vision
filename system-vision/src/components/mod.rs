//! Leptos UI components for the web frontend.

pub mod access;
pub mod camera_settings;
pub mod class_names;
pub mod common;
pub mod configuration;
pub mod control_panel;
pub mod detection_areas;
pub mod detection_models;
pub mod editing_toolbar;
pub mod flow;
pub mod image_adjust_overlay;
pub mod live_video_stream;
pub mod locale;
pub mod main_view;
pub mod popup_messages;
pub mod settings;
pub mod statistics;
pub mod status_component;
pub mod stereo_overlay;
pub mod training;
pub mod view_navigation;

pub use common::panel_header;
pub use detection_areas::add_area_button;
pub use detection_areas::area_chips;

pub use camera_settings::CameraSettings;
pub use common::header::Header;
pub use common::power_button::PowerButton;
pub use configuration::Configuration;
pub use control_panel::{ControlPanel, ViewMode};
pub use flow::Flow;
pub use live_video_stream::LiveVideoStream;
pub use main_view::MainView;
pub use popup_messages::PopupMessages;
pub use settings::{GpioSettings, NetworkSettings, Settings};
pub use statistics::PerformanceStatistics;
pub use status_component::StatusComponent;
pub use training::{TrainingConfirmModal, TrainingView};
pub use view_navigation::ViewNavigation;
