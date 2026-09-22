"""Upload validation reads the header bytes; the extension is never trusted."""
import io

import pytest
from PIL import Image

from agents import media


def png_bytes(size=(40, 40)):
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, "PNG")
    return buf.getvalue()


def jpeg_with_exif():
    im = Image.new("RGB", (40, 30), "blue")
    exif = Image.Exif()
    exif[270] = "secret description"
    exif[271] = "SecretCamera"
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()


MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


@pytest.mark.parametrize("data,expected", [
    (png_bytes(), ("png", "image")),
    (MP4, ("mp4", "video")),
])
def test_sniff_accepts_real_files(data, expected):
    assert media.sniff(data) == expected


def test_sniff_detects_webp():
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "green").save(buf, "WEBP")
    assert media.sniff(buf.getvalue()) == ("webp", "image")


@pytest.mark.parametrize("data", [
    b"not an image at all",
    b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
    b"",
    b"MZ\x90\x00",                      # a Windows executable
])
def test_sniff_rejects_everything_else(data):
    assert media.sniff(data) == (None, None)


def test_extension_is_not_trusted(tmp_path, monkeypatch):
    """A .png name over non-image bytes is still rejected."""
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(media, "MEDIA_DIR", tmp_path)
    with pytest.raises(ValueError):
        media.save_upload(b"totally not a png", 1, 1)


def test_oversized_image_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "MEDIA_DIR", tmp_path)
    too_big = png_bytes() + b"\x00" * (media.MAX_IMAGE_BYTES + 1)
    with pytest.raises(ValueError, match="too large"):
        media.save_upload(too_big, 1, 1)


def test_oversized_video_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "MEDIA_DIR", tmp_path)
    too_big = MP4 + b"\x00" * (media.MAX_VIDEO_BYTES + 1)
    with pytest.raises(ValueError, match="too large"):
        media.save_upload(too_big, 1, 1)


def test_corrupt_body_behind_a_valid_header_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "MEDIA_DIR", tmp_path)
    corrupt = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    with pytest.raises(ValueError):
        media.save_upload(corrupt, 1, 1)


def test_exif_is_stripped(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "MEDIA_DIR", tmp_path)
    raw = jpeg_with_exif()
    assert dict(Image.open(io.BytesIO(raw)).getexif()), "fixture must carry EXIF"

    path, kind = media.save_upload(raw, 7, 1)
    assert kind == "image"
    assert dict(Image.open(path).getexif()) == {}
    with open(path, "rb") as fh:
        assert b"SecretCamera" not in fh.read()


def test_saved_filename_is_generated_not_the_users(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(media, "MEDIA_DIR", tmp_path)
    path, _ = media.save_upload(png_bytes(), 42, 3)
    name = os.path.basename(path)
    assert name.startswith("42_v3_up")
    assert name.endswith(".png")
