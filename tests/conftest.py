import io

import pytest
from PIL import Image


def make_image(size=(400, 300), color=(200, 120, 60), fmt="JPEG", exif=None) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    kwargs = {"exif": exif} if exif is not None else {}
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


@pytest.fixture
def jpeg_bytes():
    return make_image()


@pytest.fixture
def payload():
    """A valid raw model payload with two items."""
    return {
        "is_food": True,
        "items": [
            {
                "name": "Chicken breast",
                "grams": 150,
                "kcal": 248,
                "kcal_low": 210,
                "kcal_high": 290,
                "protein_g": 46.5,
                "carbs_g": 0,
                "fat_g": 5.4,
            },
            {
                "name": "White rice, cooked",
                "grams": 180,
                "kcal": 234,
                "kcal_low": 190,
                "kcal_high": 290,
                "protein_g": 4.9,
                "carbs_g": 51,
                "fat_g": 0.5,
            },
        ],
        "confidence": "medium",
        "assumptions": ["1 tsp oil used for cooking"],
        "questions": ["Is the rice weighed cooked or dry?"],
    }
