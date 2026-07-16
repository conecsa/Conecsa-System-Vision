//! Training page — dataset management + on-device YOLO training.
//!
//! Replaces the dashboard entirely while `ViewMode::Training` is active.
//! Entering goes through `TrainingConfirmModal` (inference is stopped and the
//! TensorRT runtime released); the landing view is the dataset gallery
//! (create / upload / rename / delete), and opening a dataset mounts the
//! capture → label → train editor scoped to it. Exiting resumes inference.
//! On training completion the resulting conversion job is handed back to the
//! dashboard's Configuration panel via `PendingConversion`.

mod capture_panel;
mod classes_panel;
mod confirm_modal;
mod dataset_card;
mod dataset_delete_modal;
mod dataset_editor;
mod dataset_gallery;
mod dataset_name_modal;
mod dataset_upload_modal;
mod gallery;
mod label_canvas;
mod label_editor;
mod label_geometry;
mod label_sam_panel;
mod label_shapes;
mod label_toolbar;
mod progress_overlay;
mod replicate_modal;
mod train_modal;
mod training_view;

pub use confirm_modal::TrainingConfirmModal;
pub use training_view::TrainingView;
