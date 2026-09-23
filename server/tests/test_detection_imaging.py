"""Real encoded images pin what Claude receives without requiring a model call."""

import io
import json

import pytest
from PIL import Image
from pydantic import ValidationError

from app.config import Settings, settings
from app.services.detection import imaging
from scripts.eval_detection import evaluate


def encoded(image, *, orientation=None):
    buffer = io.BytesIO()
    exif = Image.Exif()
    exif[315] = "private camera owner"
    if orientation is not None:
        exif[274] = orientation
    image.save(buffer, format="PNG", exif=exif)
    return buffer.getvalue()


@pytest.mark.parametrize(
    "size,expected",
    [
        ((4000, 3000), (1024, 768)),
        ((3000, 4000), (768, 1024)),
        ((2000, 2000), (1024, 1024)),
        ((120, 80), (120, 80)),
    ],
)
def test_overviews_preserve_shape_and_never_enlarge_small_uploads(monkeypatch, size, expected):
    monkeypatch.setattr(settings, "detect_image_max_edge_px", 1024)
    prepared = imaging.prepare_image(encoded(Image.new("RGB", size, "red")))
    with Image.open(io.BytesIO(prepared)) as image:
        assert image.size == expected
        assert image.format == "JPEG"
        assert not image.getexif()


def test_overview_and_original_crop_share_the_camera_orientation(monkeypatch):
    monkeypatch.setattr(settings, "detect_image_max_edge_px", 1024)
    monkeypatch.setattr(settings, "detect_image_crop_max_edge_px", 768)
    source = Image.new("RGB", (200, 100), "red")
    source.paste("blue", (100, 0, 200, 100))
    raw = encoded(source, orientation=6)

    with Image.open(io.BytesIO(imaging.prepare_image(raw))) as overview:
        assert overview.size == (100, 200)
        assert overview.getpixel((50, 20))[0] > 240
        assert overview.getpixel((50, 180))[2] > 240
        assert not overview.getexif()
    with Image.open(io.BytesIO(imaging.crop_region(raw, 0, 0.5, 1, 0.5))) as crop:
        assert crop.size == (100, 100)
        assert crop.getpixel((50, 50))[2] > 240
        assert not crop.getexif()


@pytest.mark.parametrize("mode", ["RGBA", "P", "L"])
def test_supported_pixel_modes_are_encoded_as_readable_jpeg(mode):
    raw = encoded(Image.new(mode, (60, 40)))
    with Image.open(io.BytesIO(imaging.prepare_image(raw))) as image:
        image.load()
        assert image.format == "JPEG"
        assert image.mode in ("RGB", "L")


def test_crops_have_an_independent_size_limit_without_inventing_pixels(monkeypatch):
    monkeypatch.setattr(settings, "detect_image_max_edge_px", 1024)
    monkeypatch.setattr(settings, "detect_image_crop_max_edge_px", 768)
    raw = encoded(Image.new("RGB", (4000, 3000), "green"))
    with Image.open(io.BytesIO(imaging.crop_region(raw, 0, 0, 0.5, 0.5))) as large:
        assert large.size == (768, 576)
    with Image.open(io.BytesIO(imaging.crop_region(raw, 0, 0, 0.05, 0.05))) as small:
        assert small.size == (200, 150)


def test_outside_crop_coordinates_still_produce_a_nonempty_bounded_image(monkeypatch):
    monkeypatch.setattr(settings, "detect_image_crop_max_edge_px", 768)
    raw = encoded(Image.new("RGB", (40, 30), "green"))
    with Image.open(io.BytesIO(imaging.crop_region(raw, 2, -1, -2, 0))) as crop:
        assert crop.size == (1, 1)


def test_jpeg_quality_changes_bytes_without_changing_visual_token_estimates(monkeypatch):
    raw = encoded(Image.effect_noise((512, 384), 80).convert("RGB"))
    monkeypatch.setattr(settings, "detect_image_jpeg_quality", 88)
    high = imaging.image_stats(imaging.prepare_image(raw))
    monkeypatch.setattr(settings, "detect_image_jpeg_quality", 30)
    low = imaging.image_stats(imaging.prepare_image(raw))
    assert low["bytes"] < high["bytes"]
    assert low["visual_tokens"] == high["visual_tokens"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("detect_image_max_edge_px", 0),
        ("detect_image_max_edge_px", 3000),
        ("detect_image_crop_max_edge_px", -1),
        ("detect_image_jpeg_quality", 0),
        ("detect_image_jpeg_quality", 100),
    ],
)
def test_invalid_preprocessing_settings_fail_at_configuration_loading(field, value):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, **{field: value})
    assert any(item["loc"] == (field,) for item in error.value.errors())


async def test_offline_comparison_reports_real_dimensions_and_restores_settings(tmp_path):
    photo, report = tmp_path / "synthetic.png", tmp_path / "comparison.json"
    photo.write_bytes(encoded(Image.new("RGB", (4000, 3000), "red")))
    before = (settings.detect_image_max_edge_px, settings.detect_image_jpeg_quality)
    assert (
        await evaluate(
            1,
            None,
            photo,
            edges=[1568, 1280, 1024],
            qualities=[88, 85],
            images_only=True,
            report=report,
        )
        == 0
    )
    result = json.loads(report.read_text())
    assert result["images_only"] is True
    assert [profile["prepared"]["visual_tokens"] for profile in result["profiles"]] == [
        2352,
        1610,
        1036,
        2352,
        1610,
        1036,
    ]
    assert all(profile["runs"] == [] for profile in result["profiles"])
    assert before == (settings.detect_image_max_edge_px, settings.detect_image_jpeg_quality)
