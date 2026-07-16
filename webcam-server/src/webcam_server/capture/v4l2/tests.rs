//! Unit tests for the JPEG payload-trimming helper.
use super::super::super::WebcamServer;

#[test]
fn empty_buffer_returns_zero() {
    assert_eq!(WebcamServer::jpeg_payload_len(&[]), 0);
}

#[test]
fn single_byte_has_no_marker() {
    assert_eq!(WebcamServer::jpeg_payload_len(&[0xFF]), 1);
}

#[test]
fn missing_eoi_returns_full_length() {
    assert_eq!(WebcamServer::jpeg_payload_len(&[0xFF, 0xD8, 0x00, 0x01]), 4);
}

#[test]
fn eoi_at_the_end_keeps_full_length() {
    let buf = [0xFF, 0xD8, 0x12, 0x34, 0xFF, 0xD9];
    assert_eq!(WebcamServer::jpeg_payload_len(&buf), buf.len());
}

#[test]
fn zero_tail_after_eoi_is_trimmed() {
    // V4L2 buffers are sized to the format's full `sizeimage`, so a compressed
    // frame is followed by a large zero tail.
    let mut buf = vec![0xFF, 0xD8, 0x12, 0x34, 0xFF, 0xD9];
    let payload = buf.len();
    buf.extend_from_slice(&[0u8; 1024]);
    assert_eq!(WebcamServer::jpeg_payload_len(&buf), payload);
}

#[test]
fn last_eoi_wins_with_embedded_thumbnails() {
    // EXIF thumbnails embed their own EOI; the frame ends at the last one.
    let buf = [0xFF, 0xD8, 0xFF, 0xD9, 0x56, 0xFF, 0xD9, 0x00, 0x00];
    assert_eq!(WebcamServer::jpeg_payload_len(&buf), 7);
}
