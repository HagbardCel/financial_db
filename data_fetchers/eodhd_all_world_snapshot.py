"""Compatibility wrapper for the repo-managed EODHD downloader."""

from data_fetchers.eodhd.downloader import main


if __name__ == "__main__":
    raise SystemExit(main())
