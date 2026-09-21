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


def test_folder_dialog_returns_directory(client, tmp_path, monkeypatch):
    folder = tmp_path / "picked"
    folder.mkdir()
    monkeypatch.setattr(api_app, "pick_folder_dialog", lambda title="Select folder": str(folder))
    r = client.post("/dialog/folder", json={"title": "Select input folder"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cancelled"] is False
    assert body["path"] == str(folder.resolve())


def test_folder_dialog_cancel(client, monkeypatch):
    monkeypatch.setattr(api_app, "pick_folder_dialog", lambda title="Select folder": None)
    r = client.post("/dialog/folder", json={})
    assert r.status_code == 200
    assert r.json()["cancelled"] is True
    assert r.json()["path"] is None


def test_set_focal_auto_center_flag(client, tmp_path):
    src = _imgs(tmp_path)
    client.post("/session", json={
        "input_folder": str(src),
        "output_folder": str(tmp_path / "out"),
        "target_width": 320,
        "target_height": 180,
    })
    r = client.post("/focal", json={"x": 160, "y": 120, "index": 0, "auto_center": True})
    assert r.status_code == 200
    im = r.json()["images"][0]
    assert im["auto_center"] is True
    assert im["focal_at_center"] is True
    assert im["width"] == 320
    assert im["megapixels"] > 0


def test_preview_without_focal_does_not_set_focal(client, tmp_path):
    src = _imgs(tmp_path)
    client.post("/session", json={
        "input_folder": str(src),
        "output_folder": str(tmp_path / "out"),
        "target_width": 320,
        "target_height": 180,
    })
    assert client.get("/session").json()["images"][0]["focal"] is None
    r = client.get("/media/preview/0")
    assert r.status_code == 200
    snap = client.get("/session").json()["images"][0]
    assert snap["focal"] is None
    assert snap["completed"] is False
    assert snap["auto_center"] is False


def test_set_focal_with_crop_scale(client, tmp_path):
    src = _imgs(tmp_path)
    client.post("/session", json={
        "input_folder": str(src),
        "output_folder": str(tmp_path / "out"),
        "target_width": 160,
        "target_height": 90,
    })
    # Centered focal so zoom-out can grow while staying locked on the point.
    r = client.post("/focal", json={"x": 160, "y": 120, "index": 0, "crop_scale": 1.5})
    assert r.status_code == 200
    im = r.json()["images"][0]
    assert im["focal"] == [160.0, 120.0]
    assert abs(im["crop_scale"] - 1.5) < 1e-6
    crop = client.get("/crop/0").json()
    assert abs(crop["crop_scale"] - 1.5) < 1e-6
    assert crop["w"] > 160 or crop["h"] > 90
    assert abs((crop["x"] + crop["w"] / 2) - 160) < 2
    assert abs((crop["y"] + crop["h"] / 2) - 120) < 2


def test_set_focal_with_flips(client, tmp_path):
    src = _imgs(tmp_path)
    client.post("/session", json={
        "input_folder": str(src),
        "output_folder": str(tmp_path / "out"),
        "target_width": 160,
        "target_height": 90,
    })
    r = client.post("/focal", json={
        "x": 100, "y": 80, "index": 0, "crop_scale": 1.0,
        "flip_h": True, "flip_v": False,
    })
    assert r.status_code == 200
    im = r.json()["images"][0]
    assert im["flip_h"] is True
    assert im["flip_v"] is False
    data = json.loads((src / "focal_points.json").read_text())
    assert data["im00.jpg"]["flip_h"] is True
    assert data["im00.jpg"]["flip_v"] is False


def test_crop_scale_is_per_image(client, tmp_path):
    src = _imgs(tmp_path, 2)
    client.post("/session", json={
        "input_folder": str(src),
        "output_folder": str(tmp_path / "out"),
        "target_width": 160,
        "target_height": 90,
    })
    client.post("/focal", json={"x": 80, "y": 60, "index": 0, "crop_scale": 2.0})
    client.post("/focal", json={"x": 40, "y": 30, "index": 1, "crop_scale": 0.75})
    snap = client.get("/session").json()["images"]
    assert abs(snap[0]["crop_scale"] - 2.0) < 1e-6
    assert abs(snap[1]["crop_scale"] - 0.75) < 1e-6
    # New / unset images stay at default scale until altered.
    client.delete("/focal", params={"index": 1})
    snap = client.get("/session").json()["images"]
    assert abs(snap[0]["crop_scale"] - 2.0) < 1e-6
    assert abs(snap[1]["crop_scale"] - 1.0) < 1e-6


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


def test_focal_points_json_lives_in_input(client, tmp_path):
    src = _imgs(tmp_path, 2)
    out = tmp_path / "out"
    client.post("/session", json={
        "input_folder": str(src),
        "output_folder": str(out),
        "target_width": 160,
        "target_height": 90,
    })
    client.post("/focal", json={"x": 10, "y": 10, "index": 0})
    assert (src / "focal_points.json").exists()
    assert not (out / "focal_points.json").exists()


def test_export_cleanup_keeps_input_json(client, tmp_path):
    src = _imgs(tmp_path, 1)
    out = tmp_path / "out"
    client.post("/session", json={
        "input_folder": str(src),
        "output_folder": str(out),
        "target_width": 160,
        "target_height": 90,
    })
    client.post("/focal", json={"x": 20, "y": 20, "index": 0})
    assert (src / "focal_points.json").exists()
    dest = tmp_path / "export"
    r = client.post("/export", json={"output_folder": str(dest), "orientation": "landscape", "cleanup": True})
    assert r.status_code == 200
    assert "complete" in r.text
    assert (src / "focal_points.json").exists()


def test_duplicate_inserts_after_current(client, tmp_path):
    src = _imgs(tmp_path, 2)
    client.post("/session", json={
        "input_folder": str(src),
        "output_folder": str(tmp_path / "out"),
        "target_width": 160,
        "target_height": 90,
    })
    client.post("/focal", json={"x": 55, "y": 44, "auto_center": False, "crop_scale": 1.5, "index": 0})
    before = client.get("/session").json()
    assert before["total"] == 2
    assert before["current_idx"] == 0
    name0 = before["images"][0]["filename"]
    r = client.post("/duplicate")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3
    assert data["current_idx"] == 1
    assert data["images"][0]["filename"] == name0
    dup = data["images"][1]
    assert "__dup" in dup["filename"]
    assert (src / dup["filename"]).exists()
    assert abs(dup["crop_scale"] - 1.5) < 1e-6
    assert dup["focal"][0] == 55
    assert dup["focal"][1] == 44
    assert data["images"][2]["filename"] == before["images"][1]["filename"]
    assert (src / "focal_points.json").exists()
