//! POSIX shared-memory producer: a double-buffered frame region plus
//! protobuf-encoded config/health regions in the header (the camera SHM ring
//! consumed by the inference-service and api-gateway).

use prost::Message;
use std::sync::atomic::{AtomicU32, AtomicU64, Ordering};

/// Magic number identifying a valid conecsa SHM segment.
const SHM_MAGIC: u32 = 0xC04E_5A01;
const SHM_VERSION: u32 = 1;
const HEADER_SIZE: usize = 256;
const CONFIG_PAYLOAD_MAX: usize = 128;
const HEALTH_PAYLOAD_MAX: usize = 64;
const SHM_SLOT_MIN_BYTES_DEFAULT: usize = 8 * 1024 * 1024;

/// Offsets into the SHM header (see plan for full layout).
mod off {
    pub const MAGIC: usize = 0;
    pub const VERSION: usize = 4;
    pub const WIDTH: usize = 8;
    pub const HEIGHT: usize = 12;
    pub const CHANNELS: usize = 16;
    pub const MAX_FRAME_BYTES: usize = 20;
    pub const FRAME_WRITE_SEQ: usize = 24;
    pub const ACTIVE_SLOT: usize = 32;
    pub const FORMAT_FLAG: usize = 36;
    pub const FRAME_SIZE: usize = 40;
    // Config region
    pub const CONFIG_WRITE_SEQ: usize = 44;
    pub const CONFIG_SIZE: usize = 48;
    pub const CONFIG_PAYLOAD: usize = 52;
    // Health region (52 + 128 = 180)
    pub const HEALTH_WRITE_SEQ: usize = 180;
    pub const HEALTH_SIZE: usize = 184;
    pub const HEALTH_PAYLOAD: usize = 188;
}

/// Include prost-generated protobuf types.
pub mod proto {
    include!(concat!(env!("OUT_DIR"), "/conecsa.rs"));
}

/// Format flags written to the SHM header.
pub const FORMAT_RAW_RGB: u32 = 0;
pub const FORMAT_JPEG: u32 = 1;

/// POSIX shared-memory producer.
///
/// Creates a named SHM segment with a double-buffered frame region and
/// protobuf-encoded config/health regions in the header.
pub struct ShmProducer {
    ptr: *mut u8,
    total_size: usize,
    slot_size: usize,
    shm_name: std::ffi::CString,
    last_config_seq: u32,
}

// SAFETY: The SHM region is used from a single writer thread.  Atomic
// operations on the mapped memory handle cross-process synchronization.
unsafe impl Send for ShmProducer {}
unsafe impl Sync for ShmProducer {}

impl ShmProducer {
    /// Read slot min bytes.
    fn read_slot_min_bytes() -> usize {
        std::env::var("SHM_SLOT_MIN_BYTES")
            .ok()
            .and_then(|v| v.parse::<usize>().ok())
            .filter(|v| *v >= 1_500_000)
            .unwrap_or(SHM_SLOT_MIN_BYTES_DEFAULT)
    }

    /// Create (or re-create) the named shared-memory segment.
    pub fn new(name: &str, width: u32, height: u32) -> Result<Self, String> {
        // Compute frame size in bytes using usize and checked arithmetic to avoid overflow.
        let pixels = (width as usize)
            .checked_mul(height as usize)
            .ok_or_else(|| "frame dimensions too large".to_string())?;
        let frame_bytes = pixels
            .checked_mul(3)
            .ok_or_else(|| "frame size too large".to_string())?;
        let slot_size =
            std::cmp::max(frame_bytes, Self::read_slot_min_bytes());
        let total_size = slot_size
            .checked_mul(2)
            .and_then(|v| HEADER_SIZE.checked_add(v))
            .ok_or_else(|| "shared memory segment size too large".to_string())?;

        let shm_name = std::ffi::CString::new(format!("/{name}"))
            .map_err(|e| format!("invalid shm name: {e}"))?;

        unsafe {
            // Remove stale segment if any.
            libc::shm_unlink(shm_name.as_ptr());

            let fd = libc::shm_open(
                shm_name.as_ptr(),
                libc::O_CREAT | libc::O_RDWR | libc::O_EXCL,
                0o666,
            );
            if fd < 0 {
                return Err(format!(
                    "shm_open failed: {}",
                    std::io::Error::last_os_error()
                ));
            }

            if libc::ftruncate(fd, total_size as libc::off_t) != 0 {
                libc::close(fd);
                libc::shm_unlink(shm_name.as_ptr());
                return Err(format!(
                    "ftruncate failed: {}",
                    std::io::Error::last_os_error()
                ));
            }

            let ptr = libc::mmap(
                std::ptr::null_mut(),
                total_size,
                libc::PROT_READ | libc::PROT_WRITE,
                libc::MAP_SHARED,
                fd,
                0,
            );
            libc::close(fd);

            if ptr == libc::MAP_FAILED {
                libc::shm_unlink(shm_name.as_ptr());
                return Err(format!("mmap failed: {}", std::io::Error::last_os_error()));
            }

            let ptr = ptr as *mut u8;

            // Zero the entire region.
            std::ptr::write_bytes(ptr, 0, total_size);

            // Write header fields.
            Self::write_u32(ptr, off::MAGIC, SHM_MAGIC);
            Self::write_u32(ptr, off::VERSION, SHM_VERSION);
            Self::write_u32(ptr, off::WIDTH, width);
            Self::write_u32(ptr, off::HEIGHT, height);
            Self::write_u32(ptr, off::CHANNELS, 3);
            Self::write_u32(ptr, off::MAX_FRAME_BYTES, slot_size as u32);

            Ok(Self {
                ptr,
                total_size,
                slot_size,
                shm_name,
                last_config_seq: 0,
            })
        }
    }

    /// Publish a raw RGB frame (format_flag = 0).
    pub fn publish_frame_rgb(&self, data: &[u8], w: u32, h: u32) {
        // Never publish dimensions that cannot fit in one slot; that breaks
        // the consumer reshape path for RAW frames.
        if data.len() > self.slot_size {
            eprintln!(
                "[webcam] RAW frame dropped: {} bytes exceeds SHM slot {} bytes ({}x{})",
                data.len(),
                self.slot_size,
                w,
                h
            );
            return;
        }

        // Update header dimensions in case V4L2 negotiated a different resolution.
        unsafe {
            Self::write_u32(self.ptr, off::WIDTH, w);
            Self::write_u32(self.ptr, off::HEIGHT, h);
        }
        self.publish_frame(data, FORMAT_RAW_RGB);
    }

    /// Publish a JPEG frame (format_flag = 1).
    pub fn publish_frame_jpeg(&self, data: &[u8]) {
        self.publish_frame(data, FORMAT_JPEG);
    }

    /// Publish frame.
    fn publish_frame(&self, data: &[u8], format: u32) {
        let len = data.len().min(self.slot_size);

        unsafe {
            // Read current active slot, toggle to the other one.
            let cur = self.atomic_u32(off::ACTIVE_SLOT).load(Ordering::Relaxed);
            let new_slot = 1 - cur;

            // Write frame data into the NEW slot.
            let slot_offset = HEADER_SIZE + (new_slot as usize) * self.slot_size;
            std::ptr::copy_nonoverlapping(data.as_ptr(), self.ptr.add(slot_offset), len);

            // Update metadata, then make visible with release fence.
            Self::write_u32(self.ptr, off::FORMAT_FLAG, format);
            Self::write_u32(self.ptr, off::FRAME_SIZE, len as u32);
            self.atomic_u32(off::ACTIVE_SLOT)
                .store(new_slot, Ordering::Release);
            self.atomic_u64(off::FRAME_WRITE_SEQ)
                .fetch_add(1, Ordering::Release);
        }
    }

    /// Check whether the consumer has written a new config.  Returns the
    /// deserialized `CameraConfig` if the sequence counter advanced.
    pub fn poll_config(&mut self) -> Option<proto::CameraConfig> {
        unsafe {
            let seq = self.atomic_u32(off::CONFIG_WRITE_SEQ).load(Ordering::Acquire);
            if seq == self.last_config_seq {
                return None;
            }
            self.last_config_seq = seq;

            let size = Self::read_u32(self.ptr, off::CONFIG_SIZE) as usize;
            if size == 0 || size > CONFIG_PAYLOAD_MAX {
                return None;
            }

            let payload =
                std::slice::from_raw_parts(self.ptr.add(off::CONFIG_PAYLOAD), size);
            proto::CameraConfig::decode(payload).ok()
        }
    }

    /// Write health status into the SHM header.
    pub fn publish_health(&self, status: &proto::HealthStatus) {
        let buf = status.encode_to_vec();
        if buf.len() > HEALTH_PAYLOAD_MAX {
            return;
        }
        unsafe {
            std::ptr::copy_nonoverlapping(
                buf.as_ptr(),
                self.ptr.add(off::HEALTH_PAYLOAD),
                buf.len(),
            );
            Self::write_u32(self.ptr, off::HEALTH_SIZE, buf.len() as u32);
            self.atomic_u32(off::HEALTH_WRITE_SEQ)
                .fetch_add(1, Ordering::Release);
        }
    }

    // ── helpers ──────────────────────────────────────────────────────

    unsafe fn write_u32(base: *mut u8, offset: usize, val: u32) {
        unsafe { (base.add(offset) as *mut u32).write(val) };
    }

    unsafe fn read_u32(base: *const u8, offset: usize) -> u32 {
        unsafe { (base.add(offset) as *const u32).read() }
    }

    unsafe fn atomic_u32(&self, offset: usize) -> &AtomicU32 {
        unsafe { &*(self.ptr.add(offset) as *const AtomicU32) }
    }

    unsafe fn atomic_u64(&self, offset: usize) -> &AtomicU64 {
        unsafe { &*(self.ptr.add(offset) as *const AtomicU64) }
    }
}

impl Drop for ShmProducer {
    /// Drop.
    fn drop(&mut self) {
        unsafe {
            libc::munmap(self.ptr as *mut libc::c_void, self.total_size);
            libc::shm_unlink(self.shm_name.as_ptr());
        }
    }
}
