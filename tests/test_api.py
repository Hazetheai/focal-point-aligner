"""HTTP contract tests for the FastAPI session layer."""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import app
import api.app as api_app


def _imgs(tmp_path, n=3):
    d = tmp_path / "in"
    d.mkdir()
    for i in range(n):
        img = np.zeros((240, 320, 3), dtype=np.uint8)
        img[:] = (i * 20, 40, 80)
        cv2.imwrite(str(d / f"im{i:02d}.jpg"), img)
    return d


@pytest.fixture
def client(tmp_path, monkeypatch):
    api_app._session = None
    api_app._batch = None
    monkeypatch.setattr(api_app, "PREFS_PATH", tmp_path / "config.json")
    return TestClient(app)


def test_session_roundtrip(client, tmp_path):
    src = _imgs(tmp_path)
    r = client.post("/session", json={
        "input_folder": str(src),
        "output_folder": str(tmp_path / "out"),
        "target_width": 320,
        "target_height": 180,
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] == 3
    assert data["images"][0]["width"] == 320

    r = client.post("/focal", json={"x": 10, "y": 20, "index": 0})
    assert r.status_code == 200
    assert r.json()["images"][0]["focal"] == [10.0, 20.0]

    r = client.post("/confirm")
    assert r.status_code == 200
    assert r.json()["current_idx"] == 1
    assert list((tmp_path / "out").glob("*.jpg")) == []

    r = client.post("/order", json={"order": [2, 0, 1]})
    assert r.status_code == 200
    names = [im["filename"] for im in r.json()["images"]]
    assert names == ["im02.jpg", "im00.jpg", "im01.jpg"]

    r = client.get("/crop/0")
    assert r.status_code == 200
    assert {"x", "y", "w", "h"} <= r.json().keys()

    r = client.get("/media/original/0")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")

    r = client.get("/media/thumb/0")
    assert r.status_code == 200

    r = client.post("/navigate", json={"direction": -1, "wrap": False})
    assert r.status_code == 200

    r = client.post("/navigate", json={"index": 2})
    assert r.status_code == 200
    r = client.post("/navigate", json={"direction": 1, "wrap": False})
    assert r.status_code == 200
    assert r.json()["current_idx"] == 2


def test_export_writes_numbered_jpegs(client, tmp_path):
    src = _imgs(tmp_path, 2)
    client.post("/session", json={
        "input_folder": str(src),
        "output_folder": str(tmp_path / "out"),
        "target_width": 160,
        "target_height": 90,
    })
    client.post("/focal", json={"x": 40, "y": 30, "index": 0})
    client.post("/focal", json={"x": 80, "y": 40, "index": 1})
    dest = tmp_path / "export"
    r = client.post("/export", json={"output_folder": str(dest), "orientation": "landscape", "cleanup": False})
    assert r.status_code == 200
    body = r.text
    assert "complete" in body
    assert (dest / "0000.jpg").exists()
    assert (dest / "0001.jpg").exists()
