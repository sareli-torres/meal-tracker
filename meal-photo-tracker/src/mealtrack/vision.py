"""Image preparation, vision backends and the on-disk cache.

Flow: raw bytes -> ``prepare_image`` (validate, strip EXIF, downscale, JPEG)
-> cache lookup -> backend call (only on a miss) -> ``parse_estimate``.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from PIL import Image, ImageOps, UnidentifiedImageError

from .models import MealEstimate, parse_estimate
from .prompts import PROMPT_VERSION, REPORT_MEAL_TOOL, SYSTEM_PROMPT, build_user_text

DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_SIDE = 1568  # longest side in pixels sent to the model
JPEG_QUALITY = 88
MAX_INPUT_BYTES = 25_000_000


class ImageError(ValueError):
    """The file is not a usable image."""


class VisionError(RuntimeError):
    """The vision backend failed or returned something unusable."""


# --------------------------------------------------------------------------- images
def sniff_media_type(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"hevc", b"mif1", b"msf1"):
        raise ImageError("HEIC/HEIF photos are not supported: export the photo as JPG or PNG first")
    raise ImageError("unsupported image format (use JPG, PNG, WEBP or GIF)")


def prepare_image(data: bytes) -> bytes:
    """Return a normalized JPEG: correct orientation, no EXIF/GPS, at most ``MAX_SIDE`` px.

    Re-encoding drops all metadata, so the photo's location never leaves the machine.
    """
    if not data:
        raise ImageError("empty file")
    if len(data) > MAX_INPUT_BYTES:
        raise ImageError("image is larger than 25 MB")
    sniff_media_type(data)
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageError(f"could not read the image: {exc}") from exc

    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        img = background
    else:
        img = img.convert("RGB")

    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue()


def image_sha(prepared: bytes) -> str:
    return hashlib.sha256(prepared).hexdigest()[:16]


# --------------------------------------------------------------------------- cache
class Cache:
    """Stores the raw model payload per (image, note, model, prompt) so repeated runs are free."""

    def __init__(self, directory: Path | str | None):
        self.directory = Path(directory) if directory else None

    @staticmethod
    def key(sha: str, hint: str | None, backend: str, model: str) -> str:
        raw = f"{PROMPT_VERSION}|{backend}|{model}|{(hint or '').strip()}|{sha}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.directory:
            return None
        path = self.directory / f"{key}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def put(self, key: str, payload: dict[str, Any]) -> None:
        if not self.directory:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / f"{key}.json").write_text(json.dumps(payload), encoding="utf-8")


# --------------------------------------------------------------------------- backends
class Backend(Protocol):
    name: str
    model: str

    def estimate(self, image_jpeg: bytes, hint: str | None) -> dict[str, Any]:
        """Return the raw ``report_meal`` payload for the image."""


class ClaudeBackend:
    """Calls a vision-capable Claude model and forces a structured ``report_meal`` tool call."""

    name = "claude"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        client: Any = None,
        timeout: float = 60.0,
    ):
        self.model = model or os.getenv("MEALTRACK_MODEL") or DEFAULT_MODEL
        if client is None:
            key = api_key or os.getenv("ANTHROPIC_API_KEY")
            if not key:
                raise VisionError(
                    "ANTHROPIC_API_KEY is not set. Put it in a .env file (see .env.example) "
                    "or use --backend mock to try the app with fake data."
                )
            import anthropic

            client = anthropic.Anthropic(api_key=key, timeout=timeout)
        self.client = client

    def estimate(self, image_jpeg: bytes, hint: str | None) -> dict[str, Any]:
        data = base64.standard_b64encode(image_jpeg).decode("ascii")
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1500,
                system=SYSTEM_PROMPT,
                tools=[REPORT_MEAL_TOOL],
                tool_choice={"type": "tool", "name": REPORT_MEAL_TOOL["name"]},
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": data,
                                },
                            },
                            {"type": "text", "text": build_user_text(hint)},
                        ],
                    }
                ],
            )
        except Exception as exc:  # network errors, auth, rate limits: all surface the same way
            raise VisionError(f"Claude API call failed: {exc}") from exc

        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == REPORT_MEAL_TOOL["name"]:
                return dict(block.input)
        raise VisionError("the model did not return a structured estimate")


_MOCK_MEALS: list[dict[str, Any]] = [
    {
        "items": [
            ("Grilled chicken breast", 150, 248, 210, 290, 46.5, 0.0, 5.4),
            ("White rice, cooked", 180, 234, 190, 290, 4.9, 51.0, 0.5),
            ("Steamed broccoli", 90, 31, 25, 40, 2.5, 6.0, 0.3),
        ],
    },
    {
        "items": [
            ("Oatmeal with milk", 250, 190, 160, 240, 8.0, 30.0, 4.5),
            ("Banana", 100, 89, 75, 105, 1.1, 22.8, 0.3),
        ],
    },
    {
        "items": [
            ("Spaghetti with tomato sauce", 300, 390, 320, 480, 13.0, 75.0, 4.5),
            ("Grated parmesan", 10, 40, 30, 50, 3.6, 0.3, 2.7),
        ],
    },
    {
        "items": [
            ("Mixed green salad", 120, 25, 15, 35, 1.5, 4.0, 0.3),
            ("Hard-boiled eggs", 100, 155, 130, 180, 12.6, 1.1, 10.6),
            ("Olive oil dressing", 15, 120, 80, 150, 0.0, 0.0, 13.5),
        ],
    },
]


def mock_payload(index: int) -> dict[str, Any]:
    """A deterministic fake ``report_meal`` payload (used by the mock backend and demo data)."""
    meal = _MOCK_MEALS[index % len(_MOCK_MEALS)]
    keys = ("name", "grams", "kcal", "kcal_low", "kcal_high", "protein_g", "carbs_g", "fat_g")
    return {
        "is_food": True,
        "items": [dict(zip(keys, row)) for row in copy.deepcopy(meal["items"])],
        "confidence": "low",
        "assumptions": ["MOCK backend: placeholder values, not a real estimate"],
        "questions": [],
    }


class MockBackend:
    """Offline backend with fake data, for demos and tests. Never used unless asked for."""

    name = "mock"
    model = "mock-1"

    def estimate(self, image_jpeg: bytes, hint: str | None) -> dict[str, Any]:
        index = int(hashlib.sha256(image_jpeg).hexdigest(), 16) % len(_MOCK_MEALS)
        return mock_payload(index)


def get_backend(name: str | None = None) -> Backend:
    """``claude`` by default; ``mock`` only when explicitly requested (flag or env var)."""
    chosen = (name or os.getenv("MEALTRACK_BACKEND") or "claude").lower()
    if chosen == "claude":
        return ClaudeBackend()
    if chosen == "mock":
        return MockBackend()
    raise VisionError(f"unknown backend {chosen!r} (use 'claude' or 'mock')")


# --------------------------------------------------------------------------- orchestration
@dataclass
class Analysis:
    estimate: MealEstimate
    image_sha: str
    cached: bool
    backend: str
    model: str


def analyze_photo(
    data: bytes,
    backend: Backend,
    hint: str | None = None,
    cache: Cache | None = None,
) -> Analysis:
    """Prepare the image, call the backend (or the cache) and validate the result."""
    prepared = prepare_image(data)
    sha = image_sha(prepared)
    cache = cache or Cache(None)
    key = Cache.key(sha, hint, backend.name, backend.model)

    payload = cache.get(key)
    cached = payload is not None
    if payload is None:
        payload = backend.estimate(prepared, hint)
        # Only successful, parseable payloads are cached.
        estimate = parse_estimate(payload)
        cache.put(key, payload)
    else:
        estimate = parse_estimate(payload)

    return Analysis(
        estimate=estimate,
        image_sha=sha,
        cached=cached,
        backend=backend.name,
        model=backend.model,
    )
