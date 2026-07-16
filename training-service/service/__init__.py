"""training-service — on-device YOLO26 dataset building + training.

Control plane only: capture/labels/classes CRUD and job orchestration live
here; everything torch-heavy (ultralytics training, SAM3 segmentation) runs in
child processes so this long-lived gRPC process never accumulates allocator
state (same isolation rule as the inference-service converters).
"""
