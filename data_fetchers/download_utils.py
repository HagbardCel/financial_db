from __future__ import annotations

import re
from logging import Logger
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import parse_qs, urlparse

import requests


def use_cached_file(path: Path, refresh: bool, logger: Optional[Logger] = None) -> bool:
    if path.exists() and not refresh:
        if logger:
            logger.info("Using cached file for %s", path.name)
        return True
    return False


def download_url_to_path(url: str, destination: Path, timeout: int = 30) -> None:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)


def download_first_available_url(
    urls: Iterable[str],
    destination: Path,
    timeout: int = 30,
) -> str:
    last_error: Exception | None = None
    for url in urls:
        try:
            download_url_to_path(url, destination, timeout=timeout)
            return url
        except requests.HTTPError as exc:
            response = getattr(exc, "response", None)
            if response is not None and response.status_code == 404:
                last_error = exc
                continue
            raise
        except Exception as exc:
            last_error = exc
            continue

    if last_error:
        raise last_error
    raise ValueError("No download URLs provided.")


def parse_drive_file_id(url: str) -> Optional[str]:
    parsed = urlparse(url)
    if "drive.google.com" not in parsed.netloc:
        return None

    query_id = parse_qs(parsed.query).get("id")
    if query_id:
        return query_id[0]

    match = re.search(r"/d/([a-zA-Z0-9_-]+)", parsed.path)
    if match:
        return match.group(1)
    return None


def parse_drive_folder_id(url: str) -> Optional[str]:
    parsed = urlparse(url)
    if "drive.google.com" not in parsed.netloc:
        return None

    match = re.search(r"/folders/([a-zA-Z0-9_-]+)", parsed.path)
    if match:
        return match.group(1)
    return None


def is_download_response(response: requests.Response) -> bool:
    content_disposition = response.headers.get("content-disposition", "").lower()
    content_type = response.headers.get("content-type", "").lower()
    return (
        "attachment" in content_disposition
        or "text/csv" in content_type
        or "application/octet-stream" in content_type
        or "application/zip" in content_type
    )


def download_google_drive_file(file_id: str, destination: Path, timeout: int = 60) -> None:
    base_url = "https://drive.google.com/uc"
    with requests.Session() as session:
        params = {"export": "download", "id": file_id}
        response = session.get(base_url, params=params, timeout=timeout, stream=True)
        response.raise_for_status()

        if not is_download_response(response):
            text = response.text
            token_match = re.search(r"confirm=([0-9A-Za-z_]+)", text)
            token = next(
                (value for key, value in response.cookies.items() if key.startswith("download_warning")),
                None,
            )
            if token_match:
                token = token_match.group(1)
            if token:
                params["confirm"] = token
                response = session.get(base_url, params=params, timeout=timeout, stream=True)
                response.raise_for_status()

        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)


def download_any_url(url: str, destination: Path, timeout: int = 60) -> None:
    drive_file_id = parse_drive_file_id(url)
    if drive_file_id:
        download_google_drive_file(drive_file_id, destination, timeout=timeout)
        return
    download_url_to_path(url, destination, timeout=timeout)
