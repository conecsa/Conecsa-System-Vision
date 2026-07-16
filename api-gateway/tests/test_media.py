"""Unit tests for MJPEG frame framing."""
from gateway.media import format_mjpeg_frame


class TestFormatMjpegFrame:
    def test_wraps_with_multipart_boundary(self):
        out = format_mjpeg_frame(b"JPEGDATA")
        assert out == (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            b"JPEGDATA\r\n"
        )

    def test_starts_with_boundary(self):
        assert format_mjpeg_frame(b"x").startswith(b"--frame\r\n")

    def test_ends_with_crlf(self):
        assert format_mjpeg_frame(b"x").endswith(b"\r\n")

    def test_preserves_payload_bytes(self):
        payload = bytes(range(256))
        out = format_mjpeg_frame(payload)
        assert payload in out

    def test_empty_payload(self):
        out = format_mjpeg_frame(b"")
        assert out == b"--frame\r\nContent-Type: image/jpeg\r\n\r\n\r\n"
