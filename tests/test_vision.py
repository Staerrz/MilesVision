"""Downsample, OCR item shape, and capture paths."""

from pathlib import Path

from PIL import Image

from desktop_agent.vision.capture import capture_active_window, capture_full, capture_region
from desktop_agent.vision.downsample import fit_model, scale_geo
from desktop_agent.vision.ocr import TesseractOcr, VlmBoxOcr, words_to_items
from tests.fakes import FakeGrabber


def test_fit_model_caps_long_side() -> None:
    image = Image.new("RGB", (4000, 2000), "white")
    fitted, scale_x, scale_y = fit_model(image, max_side=2600, norm_size=0)
    assert fitted.size == (2600, 1300)
    assert scale_x == 4000 / 2600
    assert scale_y == 2000 / 1300


def test_fit_model_norm_size() -> None:
    image = Image.new("RGB", (200, 100), "white")
    fitted, scale_x, scale_y = fit_model(image, max_side=2600, norm_size=100)
    assert fitted.size == (100, 50)
    assert scale_x == 2
    assert scale_y == 2


def test_fit_model_leaves_small_images() -> None:
    image = Image.new("RGB", (80, 40), "white")
    fitted, scale_x, scale_y = fit_model(image, max_side=2600)
    assert fitted is image
    assert (scale_x, scale_y) == (1.0, 1.0)


def test_scale_geo_box() -> None:
    scaled = scale_geo({"box": [0, 0, 200, 100], "radius": 10, "label": "a"}, 2, 2)
    assert scaled["box"] == [0, 0, 100, 50]
    assert scaled["radius"] == 5
    assert scaled["label"] == "a"


def test_words_to_items_skips_empty_and_negative_conf() -> None:
    items = words_to_items(
        {
            "text": ["Hello", "", "x"],
            "left": [1, 2, 3],
            "top": [4, 5, 6],
            "width": [10, 10, 2],
            "height": [8, 8, 2],
            "conf": [95, 90, -1],
        }
    )
    assert items == [{"text": "Hello", "box_pixel": [1, 4, 11, 12], "confidence": 95.0}]


def test_tesseract_engine_uses_injected_reader() -> None:
    engine = TesseractOcr(
        reader=lambda _image, language: {
            "text": ["Hi"],
            "left": [0],
            "top": [0],
            "width": [4],
            "height": [4],
            "conf": ["80"],
        }
    )
    result = engine.read(Image.new("RGB", (8, 8)), "eng")
    assert result["engine"] == "tesseract"
    assert result["items"][0]["text"] == "Hi"
    assert result["items"][0]["box_pixel"] == [0, 0, 4, 4]


def test_vlm_engine_parses_tool_ocr_boxes() -> None:
    def poster(url: str, payload: dict, timeout: int, key: str) -> dict:
        assert url.endswith("/chat/completions")
        assert payload["model"] == "mimo-v2.5"
        assert key == "test-key"
        assert timeout == 5
        return {"choices": [{"message": {"content": '[{"text":"Ok","box":[1,2,3,4]}]'}}]}

    engine = VlmBoxOcr("https://example.test/v1", "test-key", "mimo-v2.5", timeout=5, poster=poster)
    result = engine.read(Image.new("RGB", (10, 10)))
    assert result["engine"] == "vlm"
    assert result["items"][0]["box_pixel"] == [1, 2, 3, 4]


def test_capture_full_region_and_window(tmp_path: Path) -> None:
    grabber = FakeGrabber()
    full = capture_full(grabber, tmp_path, max_side=100)
    assert full.size == (320, 200)
    assert full.model_size[0] <= 100
    assert full.path.is_file()
    assert full.model_path.is_file()
    assert full.region is None

    region = capture_region(grabber, tmp_path, 1, 2, 21, 12)
    assert region.size == (20, 10)
    assert region.region == (1, 2, 21, 12)

    window = capture_active_window(grabber, tmp_path)
    assert window.window_title == "Notepad"
    assert window.region == (5, 6, 105, 86)
    assert window.size == (100, 80)
