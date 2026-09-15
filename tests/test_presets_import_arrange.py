"""Tests for target retarget, import download helpers, and color AutoArrange."""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import app
import api.app as api_app
from arrange_auto import classify_dominant_color, sort_indices_by_color
from import_download import download_from_sources, parse_pasted_urls, sanitize_filename


def _imgs(tmp_path, n=3, colors=None):
    d = tmp_path / "in"
    d.mkdir()
    colors = colors or [(40, 40, 200), (40, 200, 40), (200, 40, 40)]
    for i in range(n):
        img = np.zeros((240, 320, 3), dtype=np.uint8)
        img[:] = colors[i % len(colors)]
        cv2.imwrite(str(d / f"im{i:02d}.jpg"), img)
    return d


@pytest.fixture
def client(tmp_path, monkeypatch):
    api_app._session = None
    api_app._batch = None
    monkeypatch.setattr(api_app, "PREFS_PATH", tmp_path / "config.json")
    return TestClient(app)


def test_parse_pasted_urls():
    text = "https://a.com/1.jpg\n# comment\nhttps://b.com/2.png\nnot-a-url\n"
    assert parse_pasted_urls(text) == ["https://a.com/1.jpg", "https://b.com/2.png"]


def test_sanitize_filename():
    assert ".." not in sanitize_filename("foo/../bar.jpg")


def test_set_session_target(client, tmp_path):
    src = _imgs(tmp_path)
    client.post("/session", json={
        "input_folder": str(src),
        "output_folder": str(tmp_path / "out"),
        "target_width": 2560,
        "target_height": 1440,
    })
    r = client.post("/session/target", json={"target_width": 1920, "target_height": 1080})
    assert r.status_code == 200
    data = r.json()
    assert data["target_width"] == 1920
    assert data["target_height"] == 1080
    prefs = client.get("/prefs").json()
    assert prefs["target_width"] == 1920


def test_import_download_paste(client, tmp_path, monkeypatch):
    dest = tmp_path / "dl"
    dest.mkdir()

    def fake_download(urls, folder, failed_urls=None, force=False, progress=None):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        img = np.zeros((32, 32, 3), dtype=np.uint8)
        cv2.imwrite(str(folder / "x.jpg"), img)
        if progress:
            progress(1, 1, "x.jpg")
        return {"skipped": False, "downloaded": 1, "failed": 0}

    monkeypatch.setattr("import_download.download_images", fake_download)
    r = client.post("/import/download", json={
        "dest": str(dest),
        "name": "cats",
        "urls": ["https://example.com/a.jpg"],
    })
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    events = []
    for line in r.text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    assert events, "expected SSE events"
    assert any(e.get("phase") == "download" for e in events)
    body = events[-1]
    assert body.get("complete") is True
    assert body["root"] == str(dest.resolve())
    assert any(f["name"] == "cats" for f in body["folders"])
    assert (dest / "cats" / "x.jpg").exists()


def test_color_sort_white_before_blue(tmp_path):
    white = tmp_path / "w.jpg"
    blue = tmp_path / "b.jpg"
    img_w = np.full((100, 100, 3), 250, dtype=np.uint8)
    img_b = np.zeros((100, 100, 3), dtype=np.uint8)
    img_b[:, :] = (200, 40, 40)  # BGR mostly blue-ish
    cv2.imwrite(str(white), img_w)
    cv2.imwrite(str(blue), img_b)
    label_w, _ = classify_dominant_color(white)
    assert "white" in label_w
    order, labels = sort_indices_by_color([blue, white])
    assert order[0] == 1  # white first


def test_arrange_slot_recall(client, tmp_path):
    src = _imgs(tmp_path, 3)
    client.post("/session", json={
        "input_folder": str(src),
        "output_folder": str(tmp_path / "out"),
        "target_width": 160,
        "target_height": 90,
    })
    # Reverse order into slot 1
    r = client.post("/order", json={"order": [2, 1, 0]})
    assert r.status_code == 200
    names = [im["filename"] for im in r.json()["images"]]
    client.post("/arrange/slot", json={"slot": "1", "order_names": names})
    # Restore original
    r0 = client.post("/arrange/recall", json={"slot": "original"})
    assert r0.status_code == 200
    orig = [im["filename"] for im in r0.json()["images"]]
    assert orig != names
    # Recall slot 1
    r1 = client.post("/arrange/recall", json={"slot": "1"})
    assert [im["filename"] for im in r1.json()["images"]] == names
    assert r1.json()["arrangement_active"] == "1"


def _sse_events(response):
    """Parse SSE data payloads from a TestClient StreamingResponse."""
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    events = []
    for block in response.text.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def _sse_last(response):
    events = _sse_events(response)
    assert events, "expected SSE events"
    return events[-1]


def test_auto_arrange_color(client, tmp_path):
    src = _imgs(tmp_path, 3, colors=[(200, 40, 40), (250, 250, 250), (40, 200, 40)])
    client.post("/session", json={
        "input_folder": str(src),
        "output_folder": str(tmp_path / "out"),
        "target_width": 160,
        "target_height": 90,
    })
    r = client.post("/arrange/auto", json={"mode": "color", "slot": "2"})
    events = _sse_events(r)
    assert any(ev.get("phase") == "progress" for ev in events)
    last = events[-1]
    assert last.get("complete") is True
    assert last.get("phase") == "complete"
    assert last["arrangement_active"] == "2"
    assert "2" in last["arrangements"]


def test_auto_arrange_depth_error_streams(client, tmp_path, monkeypatch):
    src = _imgs(tmp_path, 2)
    client.post("/session", json={
        "input_folder": str(src),
        "output_folder": str(tmp_path / "out"),
        "target_width": 160,
        "target_height": 90,
    })

    def boom():
        raise RuntimeError("depth model unavailable")

    monkeypatch.setattr("arrange_auto._ensure_depth_model", boom)
    r = client.post("/arrange/auto", json={"mode": "depth", "slot": "3"})
    last = _sse_last(r)
    assert last.get("phase") == "error"
    assert "depth" in str(last.get("error", "")).lower()


def test_auto_arrange_faces_error_streams(client, tmp_path, monkeypatch):
    src = _imgs(tmp_path, 2)
    client.post("/session", json={
        "input_folder": str(src),
        "output_folder": str(tmp_path / "out"),
        "target_width": 160,
        "target_height": 90,
    })

    def boom():
        raise RuntimeError("face model unavailable")

    monkeypatch.setattr("arrange_auto._ensure_face_model", boom)
    r = client.post("/arrange/auto", json={"mode": "faces", "slot": "4"})
    last = _sse_last(r)
    assert last.get("phase") == "error"
    assert "face" in str(last.get("error", "")).lower()


def test_auto_arrange_faces_stubbed(client, tmp_path, monkeypatch):
    src = _imgs(tmp_path, 3)
    client.post("/session", json={
        "input_folder": str(src),
        "output_folder": str(tmp_path / "out"),
        "target_width": 160,
        "target_height": 90,
    })
    # Return fixed centroids without loading YuNet
    xs = {0: 0.9, 1: 0.1, 2: 0.5}

    def fake_sort(paths, progress=None):
        order = sorted(range(len(paths)), key=lambda i: xs.get(i, 1e9))
        if progress:
            for i, p in enumerate(paths):
                progress(i + 1, len(paths), Path(p).name)
        return order

    monkeypatch.setattr("arrange_auto.sort_indices_by_faces", fake_sort)
    r = client.post("/arrange/auto", json={"mode": "faces", "slot": "5"})
    last = _sse_last(r)
    assert last.get("phase") == "complete"
    assert last["arrangement_active"] == "5"


def test_arrange_reverse_in_place(client, tmp_path):
    src = _imgs(tmp_path, 3)
    client.post("/session", json={
        "input_folder": str(src),
        "output_folder": str(tmp_path / "out"),
        "target_width": 160,
        "target_height": 90,
    })
    r = client.post("/arrange/auto", json={"mode": "color", "slot": "2"})
    last = _sse_last(r)
    assert last.get("phase") == "complete"
    before = [im["filename"] for im in last["images"]]
    active = last["arrangement_active"]
    slots_before = set(last["arrangements"].keys())
    assert last.get("arrangement_reversed") is False
    rev = client.post("/arrange/reverse")
    assert rev.status_code == 200
    after = [im["filename"] for im in rev.json()["images"]]
    assert after == list(reversed(before))
    assert rev.json()["arrangement_active"] == active
    assert set(rev.json()["arrangements"].keys()) == slots_before
    assert rev.json()["arrangements"][active] == after
    assert rev.json().get("arrangement_reversed") is True
    rev2 = client.post("/arrange/reverse")
    assert rev2.status_code == 200
    assert [im["filename"] for im in rev2.json()["images"]] == before
    assert rev2.json().get("arrangement_reversed") is False
