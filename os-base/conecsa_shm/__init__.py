"""conecsa_shm — shared POSIX shared-memory ring helpers.

Installed into the `conecsa-os:base` image so every `FROM base` service
(inference-service, api-gateway) imports ONE implementation of the camera and
processed-frame ring layouts instead of duplicating the header parsing.

- ``camera_ring.CameraRingReader``    — reads the webcam-server camera ring.
- ``processed_ring.ProcessedFrameWriter`` / ``ProcessedFrameReader`` — the
  inference→gateway processed-JPEG ring.
- ``stereo.combine_stereo``           — side-by-side stereo blend (pure
  function), so dataset capture / previews match the live detector's view.

Pure struct + numpy/cv2; no protobuf dependency (the camera config/health
payloads cross as opaque bytes — the caller owns the schema).
"""
