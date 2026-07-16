//! Camera format enumeration: publishes the V4L2 capture formats of every
//! visible `/dev/video*` node as JSON for the inference-service and UI.

use super::super::WebcamServer;

impl WebcamServer {
    /// Enumerate the V4L2 capture formats of every visible `/dev/video*` node
    /// and write them as JSON to a path shared with the inference-service
    /// (`/dev/shm` is shared via the common IPC namespace). The UI uses this to
    /// offer only valid resolution@fps combinations instead of free-form input
    /// that silently falls back. Best-effort: failures are logged and ignored.
    ///
    /// Layout: `{ "/dev/video0": [ {format,width,height,fps:[..]}, ... ], ... }`.
    pub(crate) fn write_camera_formats_json(path: &str) {
        use v4l::frameinterval::FrameIntervalEnum;
        use v4l::video::Capture as _;

        let mut devices = serde_json::Map::new();
        for index in 0..10u32 {
            let dev_path = format!("/dev/video{index}");
            if !std::path::Path::new(&dev_path).exists() {
                continue;
            }
            let Ok(dev) = v4l::Device::with_path(&dev_path) else {
                continue;
            };
            let Ok(descs) = dev.enum_formats() else {
                continue;
            };

            let mut entries: Vec<serde_json::Value> = Vec::new();
            for desc in descs {
                let fourcc = std::str::from_utf8(&desc.fourcc.repr)
                    .unwrap_or("????")
                    .trim_end_matches('\0')
                    .to_string();
                let Ok(sizes) = dev.enum_framesizes(desc.fourcc) else {
                    continue;
                };
                for size in sizes {
                    for d in size.size.to_discrete() {
                        let mut fps: Vec<u32> = Vec::new();
                        if let Ok(intervals) = dev.enum_frameintervals(desc.fourcc, d.width, d.height)
                        {
                            for iv in intervals {
                                if let FrameIntervalEnum::Discrete(fr) = iv.interval {
                                    if fr.numerator > 0 {
                                        fps.push(fr.denominator / fr.numerator);
                                    }
                                }
                            }
                        }
                        fps.sort_unstable_by(|a, b| b.cmp(a));
                        fps.dedup();
                        entries.push(serde_json::json!({
                            "format": fourcc,
                            "width": d.width,
                            "height": d.height,
                            "fps": fps,
                        }));
                    }
                }
            }

            if !entries.is_empty() {
                devices.insert(dev_path, serde_json::Value::Array(entries));
            }
        }

        let json = serde_json::Value::Object(devices).to_string();
        match std::fs::write(path, &json) {
            Ok(()) => eprintln!("[webcam] Camera formats written to {path}"),
            Err(e) => eprintln!("[webcam] Failed to write camera formats to {path}: {e}"),
        }
    }
}
