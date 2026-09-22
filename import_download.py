"""Download images from URL lists — vendored from imgtools (download-only).

Uses httpx instead of requests. Folder naming is driven by a user-defined
pattern (default ``image_urls--{name}``) so list files like
``image_urls--cats.txt`` download into ``cats/``.
"""

from __future__ import annotations

import os
import re
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import unquote, urlparse

import httpx

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_NAME_PATTERN = "image_urls--{name}"
DEFAULT_FOLDER_TEMPLATE = "{name}"

# Tokens available in the download-folder template (after {name} is extracted).
FOLDER_TEMPLATE_TOKENS = (
    ("{name}", "Captured name from the list filename"),
    ("{n}", "1-based index among lists in this download (1, 2, 3…)"),
    ("{nn}", "Zero-padded two-digit index (01, 02, 03…)"),
    ("{stem}", "Full list filename without extension"),
)


def sanitize_filename(filename: str) -> str:
    name, ext = os.path.splitext(filename)
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name + ext


def get_filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    parts = parsed.path.rstrip("/").split("/")
    filename = parts[-1] if parts[-1] else "image"
    filename = unquote(filename)
    if not os.path.splitext(filename)[1]:
        filename = f"{filename}.jpg"
    return sanitize_filename(filename)


def get_image_dimensions(image_data: bytes) -> Optional[str]:
    if not PIL_AVAILABLE:
        return None
    try:
        img = Image.open(BytesIO(image_data))
        return f"{img.width}x{img.height}"
    except Exception:
        return None


def is_valid_image_data(image_data: bytes):
    stripped = image_data.lstrip() if image_data else b""
    if stripped[:5].lower() == b"<html" or stripped[:6].lower() == b"<!doc" or stripped[:2] == b"<!":
        return False, "HTML document (login/block page)"
    if not PIL_AVAILABLE:
        return True, ""
    try:
        img = Image.open(BytesIO(image_data))
        img.verify()
        img2 = Image.open(BytesIO(image_data))
        img2.load()
        if img2.width == 0 or img2.height == 0:
            return False, "zero-size image"
        return True, ""
    except Exception as e:
        return False, f"PIL decode failed: {e}"


def download_images(
    urls,
    folder,
    failed_urls=None,
    force=False,
    progress: Optional[Callable[[int, int, str], None]] = None,
):
    if failed_urls is None:
        failed_urls = []
    folder = Path(folder)
    if not force and folder.exists() and any(folder.iterdir()):
        return {"skipped": True, "downloaded": 0, "failed": 0}
    folder.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    total = len(urls)
    with httpx.Client(timeout=30.0, headers=REQUEST_HEADERS, follow_redirects=True) as client:
        for i, url in enumerate(urls):
            try:
                response = client.get(url)
                response.raise_for_status()
                content_type = (response.headers.get("Content-Type") or "").lower()
                if content_type and "text/html" in content_type:
                    raise ValueError(f"Content-Type is HTML ({content_type})")
                if content_type and content_type.startswith("text/") and "image" not in content_type:
                    raise ValueError(f"Content-Type is text ({content_type})")
                image_data = response.content
                valid, reason = is_valid_image_data(image_data)
                if not valid:
                    raise ValueError(f"Invalid image data: {reason}")
                base_filename = get_filename_from_url(url)
                name_without_ext, ext = os.path.splitext(base_filename)
                dimensions = get_image_dimensions(image_data)
                if dimensions:
                    filename = f"{name_without_ext}_{dimensions}_{i}{ext}"
                else:
                    filename = f"{name_without_ext}_{i}{ext}"
                filepath = folder / filename
                filepath.write_bytes(image_data)
                downloaded += 1
                if progress:
                    progress(i + 1, total, filename)
            except Exception:
                failed_urls.append(url)
                if progress:
                    progress(i + 1, total, f"failed:{url[:48]}")
    return {"skipped": False, "downloaded": downloaded, "failed": len(failed_urls)}


def extract_folder_name_from_filename(
    input_file: str,
    pattern: Optional[str] = None,
) -> Optional[str]:
    """Derive a download folder name from a URL-list filename.

    ``pattern`` uses ``{name}`` as the capture token (default
    ``image_urls--{name}``). Without ``{name}``, ``pattern`` is treated as a
    literal prefix and the remainder of the stem becomes the folder name.
    Falls back to a legacy ``--`` split, then ``None``.
    """
    basename = os.path.basename(input_file)
    stem = os.path.splitext(basename)[0]
    pat = (pattern or DEFAULT_NAME_PATTERN).strip() or DEFAULT_NAME_PATTERN

    if "{name}" in pat:
        parts = pat.split("{name}")
        regex = "^" + "".join(
            re.escape(part) + ("(.+)" if i < len(parts) - 1 else "")
            for i, part in enumerate(parts)
        ) + "$"
        m = re.match(regex, stem)
        if m:
            captured = (m.group(1) or "").strip("_- ")
            return captured or None
    elif pat and stem.startswith(pat):
        rest = stem[len(pat):].strip("_- ")
        return rest or None

    # Legacy: anything after the first "--"
    if "--" in stem:
        rest = stem.split("--", 1)[1].strip("_- ")
        return rest or None
    return None


def format_folder_name(
    template: Optional[str],
    *,
    name: str,
    stem: str = "",
    index: int = 1,
) -> str:
    """Fill ``{name}`` / ``{n}`` / ``{nn}`` / ``{stem}`` in a folder template."""
    tpl = (template or DEFAULT_FOLDER_TEMPLATE).strip() or DEFAULT_FOLDER_TEMPLATE
    idx = max(1, int(index))
    out = (
        tpl
        .replace("{name}", str(name or "imported"))
        .replace("{nn}", f"{idx:02d}")
        .replace("{n}", str(idx))
        .replace("{stem}", str(stem or name or "imported"))
    )
    out = re.sub(r"[^a-zA-Z0-9._-]+", "_", out)
    out = re.sub(r"_+", "_", out).strip("._-")
    return out or (str(name or "imported").strip() or "imported")


def find_url_files_in_folder(folder_path: str):
    folder = Path(folder_path)
    return sorted(str(p) for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".txt")


def read_urls_from_file(filepath: str):
    try:
        text = Path(filepath).read_text(encoding="utf-8", errors="replace")
        return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
    except Exception:
        return []


def write_failed_urls_to_file(failed_urls_dict, base_path="."):
    if not failed_urls_dict or all(not urls for urls in failed_urls_dict.values()):
        return None
    failed_file = Path(base_path) / "failed_downloads.txt"
    with open(failed_file, "w", encoding="utf-8") as f:
        for folder_name, urls in failed_urls_dict.items():
            if urls:
                f.write(f"{folder_name}\n")
                for url in urls:
                    f.write(f"{url}\n")
                f.write("\n")
    return str(failed_file)


def parse_pasted_urls(text: str):
    urls = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("http://") or line.startswith("https://"):
            urls.append(line)
    return urls


def download_from_sources(
    dest: str,
    *,
    name: Optional[str] = None,
    urls: Optional[list[str]] = None,
    url_file: Optional[str] = None,
    url_folder: Optional[str] = None,
    name_pattern: Optional[str] = None,
    folder_template: Optional[str] = None,
    force: bool = False,
    progress: Optional[Callable[[dict], None]] = None,
):
    """Download into dest. Returns {root, folders, failed_file, totals}."""
    dest_path = Path(dest).expanduser().resolve()
    dest_path.mkdir(parents=True, exist_ok=True)
    failed_dict = {}
    folders = []
    total_urls = 0
    total_downloaded = 0
    total_failed = 0
    pattern = (name_pattern or DEFAULT_NAME_PATTERN).strip() or DEFAULT_NAME_PATTERN
    template = (folder_template or DEFAULT_FOLDER_TEMPLATE).strip() or DEFAULT_FOLDER_TEMPLATE

    # jobs: list of (raw_name, stem, urls)
    jobs = []
    if urls:
        folder_name = (name or "imported").strip() or "imported"
        jobs.append((folder_name, folder_name, list(urls)))
    if url_file:
        path = Path(url_file).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Not a file: {path}")
        raw = extract_folder_name_from_filename(str(path), pattern) or path.stem
        jobs.append((raw, path.stem, read_urls_from_file(str(path))))
    if url_folder:
        folder = Path(url_folder).expanduser().resolve()
        if not folder.is_dir():
            raise NotADirectoryError(f"Not a directory: {folder}")
        for txt in find_url_files_in_folder(str(folder)):
            path = Path(txt)
            raw = extract_folder_name_from_filename(txt, pattern) or path.stem
            jobs.append((raw, path.stem, read_urls_from_file(txt)))

    if not jobs:
        raise ValueError("Provide urls, url_file, or url_folder")

    for job_index, (raw_name, stem, job_urls) in enumerate(jobs, start=1):
        if not job_urls:
            continue
        folder_name = format_folder_name(
            template, name=raw_name, stem=stem, index=job_index,
        )
        out = dest_path / folder_name
        failed = []
        total_urls += len(job_urls)

        def _prog(done, total, label, _fn=folder_name):
            if progress:
                progress({
                    "folder": _fn,
                    "done": done,
                    "total": total,
                    "label": label,
                })

        result = download_images(job_urls, out, failed, force=force, progress=_prog)
        total_downloaded += result.get("downloaded", 0)
        total_failed += len(failed)
        if failed:
            failed_dict[folder_name] = failed
        folders.append({"name": folder_name, "path": str(out), **result, "url_count": len(job_urls)})

    failed_file = write_failed_urls_to_file(failed_dict, str(dest_path))
    return {
        "root": str(dest_path),
        "folders": folders,
        "failed_file": failed_file,
        "total_urls": total_urls,
        "total_downloaded": total_downloaded,
        "total_failed": total_failed,
        "name_pattern": pattern,
        "folder_template": template,
    }
