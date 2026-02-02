from __future__ import annotations

import re
from logging import Logger
from typing import Dict, List, Optional, Sequence, Tuple

import requests

from data_fetchers.download_utils import parse_drive_file_id, parse_drive_folder_id
from data_fetchers.open_asset_pricing_registry import DATA_PAGE_URL

_ANCHOR_RE = re.compile(
    r'<a[^>]*href=["\'](?P<url>https?://drive\.google\.com/[^"\']+)["\'][^>]*>(?P<label>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def extract_data_page_drive_links(html_text: str) -> List[Tuple[str, str]]:
    links: List[Tuple[str, str]] = []
    for match in _ANCHOR_RE.finditer(html_text):
        raw_label = match.group("label")
        label = _TAG_RE.sub("", raw_label).strip()
        links.append((match.group("url"), label))
    return links


def extract_data_page_drive_link(html_text: str, label: str) -> Optional[str]:
    lower_label = label.lower()
    for url, anchor_label in extract_data_page_drive_links(html_text):
        if lower_label in anchor_label.lower():
            return url
    return None


def discover_data_page_drive_link(label: str, timeout: int = 30) -> Optional[str]:
    response = requests.get(DATA_PAGE_URL, timeout=timeout)
    response.raise_for_status()
    return extract_data_page_drive_link(response.text, label)


def discover_data_page_drive_links(timeout: int = 30) -> List[Tuple[str, str]]:
    response = requests.get(DATA_PAGE_URL, timeout=timeout)
    response.raise_for_status()
    return extract_data_page_drive_links(response.text)


def _pick_best_candidate(
    links: Sequence[Tuple[str, str]],
    labels: Sequence[str],
) -> Optional[str]:
    wanted = [label.lower() for label in labels if label]
    if not wanted:
        return None
    for url, anchor_label in links:
        lower_anchor = anchor_label.lower()
        if any(label in lower_anchor for label in wanted):
            return url
    return None


def resolve_dataset_download_url(
    dataset: Dict[str, str],
    url_override: Optional[str],
    logger: Optional[Logger] = None,
) -> str:
    if url_override:
        return url_override

    labels = [
        dataset.get("data_page_label", ""),
        dataset.get("data_page_alt_label", ""),
    ]
    try:
        links = discover_data_page_drive_links()
    except Exception as exc:
        links = []
        if logger:
            logger.warning(
                "Could not fetch %s for latest links: %s. Falling back to configured ids.",
                DATA_PAGE_URL,
                exc,
            )

    discovered = _pick_best_candidate(links, labels)
    if discovered and parse_drive_file_id(discovered):
        return discovered

    if discovered and parse_drive_folder_id(discovered):
        for url, anchor_label in links:
            if parse_drive_file_id(url) and "zip" in anchor_label.lower():
                if logger:
                    logger.info(
                        "Resolved folder link to downloadable zip via data page label '%s'.",
                        anchor_label,
                    )
                return url
        raise ValueError(
            "Open Asset Pricing daily link currently points to a Google Drive folder. "
            "Provide a direct CSV/ZIP file URL via --factors-url."
        )

    if dataset.get("file_id"):
        return f"https://drive.google.com/file/d/{dataset['file_id']}/view?usp=sharing"
    if dataset.get("folder_id"):
        return f"https://drive.google.com/drive/folders/{dataset['folder_id']}?usp=sharing"
    raise ValueError("No download URL configured for dataset.")
