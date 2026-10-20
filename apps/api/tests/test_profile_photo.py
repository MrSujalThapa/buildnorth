from io import BytesIO
from uuid import uuid4

import pytest

from fastapi.testclient import TestClient
from PIL import Image

from helpers import isolated_app
from personal_markets.profile.photo_store import InMemoryPhotoStore, get_photo_store


@pytest.mark.asyncio
async def test_photo_store_separates_owners() -> None:
    store = InMemoryPhotoStore()
    first, second = uuid4(), uuid4()
    await store.put(first, b"photo")
    assert await store.get(first) == b"photo"
    assert await store.get(second) is None
    await store.delete(second)
    assert await store.get(first) == b"photo"


def test_profile_photo_upload_is_validated_and_owner_scoped() -> None:
    get_photo_store.cache_clear()
    image = BytesIO()
    Image.new("RGB", (32, 32), "#117b75").save(image, format="PNG")
    app = isolated_app()
    with TestClient(app) as client:
        bad = client.put("/api/v1/profile/photo", files={"file": ("bad.png", b"not an image", "image/png")})
        assert bad.status_code == 422
        saved = client.put("/api/v1/profile/photo", files={"file": ("photo.png", image.getvalue(), "image/png")})
        assert saved.status_code == 200
        loaded = client.get("/api/v1/profile/photo")
        assert loaded.status_code == 200
        assert loaded.headers["content-type"] == "image/webp"
        assert loaded.content[:4] == b"RIFF"
        assert client.delete("/api/v1/profile/photo").status_code == 200
        assert client.get("/api/v1/profile/photo").status_code == 404
