import base64
import io
from types import SimpleNamespace

import pytest
from PIL import Image

from mealtrack.models import EstimateError
from mealtrack.vision import (
    Cache,
    ClaudeBackend,
    ImageError,
    MockBackend,
    VisionError,
    analyze_photo,
    get_backend,
    prepare_image,
)

from conftest import make_image


# ----------------------------------------------------------------- image preparation
def test_large_images_are_downscaled_to_jpeg():
    out = prepare_image(make_image(size=(4000, 3000), fmt="PNG"))
    img = Image.open(io.BytesIO(out))
    assert img.format == "JPEG" and max(img.size) == 1568


def test_small_images_keep_their_size():
    img = Image.open(io.BytesIO(prepare_image(make_image(size=(400, 300)))))
    assert img.size == (400, 300)


def test_orientation_is_applied_and_exif_is_stripped():
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees
    exif[0x010F] = "SomePhone"
    out = Image.open(io.BytesIO(prepare_image(make_image(size=(200, 100), exif=exif))))
    assert out.size == (100, 200)
    assert len(out.getexif()) == 0


def test_transparent_png_is_flattened_on_white():
    buf = io.BytesIO()
    Image.new("RGBA", (50, 50), (255, 0, 0, 0)).save(buf, format="PNG")
    out = Image.open(io.BytesIO(prepare_image(buf.getvalue())))
    assert out.getpixel((10, 10)) == (255, 255, 255)


def test_heic_gets_a_helpful_error():
    fake_heic = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 32
    with pytest.raises(ImageError, match="HEIC"):
        prepare_image(fake_heic)


@pytest.mark.parametrize("data", [b"", b"not an image at all", b"\xff\xd8\xff garbage"])
def test_garbage_is_rejected(data):
    with pytest.raises(ImageError):
        prepare_image(data)


# ----------------------------------------------------------------- analyze + cache
class CountingBackend:
    name, model = "fake", "fake-1"

    def __init__(self, payload):
        self.payload, self.calls = payload, 0

    def estimate(self, image_jpeg, hint):
        self.calls += 1
        return self.payload


def test_second_identical_request_is_served_from_cache(tmp_path, jpeg_bytes, payload):
    backend, cache = CountingBackend(payload), Cache(tmp_path)
    first = analyze_photo(jpeg_bytes, backend, hint="rice 90 g", cache=cache)
    second = analyze_photo(jpeg_bytes, backend, hint="rice 90 g", cache=cache)
    assert (first.cached, second.cached, backend.calls) == (False, True, 1)
    assert first.estimate.kcal == second.estimate.kcal == 482.0


def test_a_different_hint_is_a_different_cache_entry(tmp_path, jpeg_bytes, payload):
    backend, cache = CountingBackend(payload), Cache(tmp_path)
    analyze_photo(jpeg_bytes, backend, hint=None, cache=cache)
    analyze_photo(jpeg_bytes, backend, hint="with extra oil", cache=cache)
    assert backend.calls == 2


def test_invalid_payloads_are_not_cached(tmp_path, jpeg_bytes):
    backend = CountingBackend({"is_food": True, "items": []})
    with pytest.raises(EstimateError):
        analyze_photo(jpeg_bytes, backend, cache=Cache(tmp_path))
    assert list(tmp_path.glob("*.json")) == []


def test_no_cache_directory_means_no_caching(jpeg_bytes, payload):
    backend = CountingBackend(payload)
    analyze_photo(jpeg_bytes, backend, cache=Cache(None))
    analyze_photo(jpeg_bytes, backend, cache=Cache(None))
    assert backend.calls == 2


# ----------------------------------------------------------------- Claude backend
class FakeClient:
    def __init__(self, content=None, error=None):
        self.content, self.error, self.requests = content, error, []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(content=self.content)


def tool_block(payload):
    return SimpleNamespace(type="tool_use", name="report_meal", input=payload)


def test_claude_backend_sends_image_and_forces_the_tool(payload, jpeg_bytes):
    client = FakeClient([SimpleNamespace(type="text", text="..."), tool_block(payload)])
    backend = ClaudeBackend(model="some-model", client=client)
    result = backend.estimate(jpeg_bytes, hint="rice 90 g")

    assert result == payload
    req = client.requests[0]
    assert req["model"] == "some-model"
    assert req["tool_choice"] == {"type": "tool", "name": "report_meal"}
    assert req["tools"][0]["name"] == "report_meal"
    image, text = req["messages"][0]["content"]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/jpeg"
    assert base64.b64decode(image["source"]["data"]) == jpeg_bytes
    assert "rice 90 g" in text["text"]


def test_claude_backend_without_a_structured_answer_fails(jpeg_bytes):
    backend = ClaudeBackend(client=FakeClient([SimpleNamespace(type="text", text="no")]))
    with pytest.raises(VisionError, match="structured"):
        backend.estimate(jpeg_bytes, None)


def test_claude_backend_wraps_api_errors(jpeg_bytes):
    backend = ClaudeBackend(client=FakeClient(error=RuntimeError("rate limited")))
    with pytest.raises(VisionError, match="rate limited"):
        backend.estimate(jpeg_bytes, None)


def test_claude_backend_needs_an_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(VisionError, match="ANTHROPIC_API_KEY"):
        ClaudeBackend()


def test_model_can_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("MEALTRACK_MODEL", "env-model")
    assert ClaudeBackend(client=FakeClient([])).model == "env-model"


# ----------------------------------------------------------------- backend selection
def test_mock_is_only_used_when_asked_for(monkeypatch):
    monkeypatch.delenv("MEALTRACK_BACKEND", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(VisionError):  # default is claude, which needs a key: no silent fake data
        get_backend()
    assert isinstance(get_backend("mock"), MockBackend)
    monkeypatch.setenv("MEALTRACK_BACKEND", "mock")
    assert isinstance(get_backend(), MockBackend)


def test_unknown_backend_name(monkeypatch):
    with pytest.raises(VisionError, match="unknown backend"):
        get_backend("gpt")


def test_mock_backend_is_deterministic_and_valid(jpeg_bytes):
    a = analyze_photo(jpeg_bytes, MockBackend())
    b = analyze_photo(jpeg_bytes, MockBackend())
    assert a.estimate.kcal == b.estimate.kcal > 0
    assert a.estimate.warnings == []
