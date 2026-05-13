# Phase 4 Implementation Plan: Robust Path Handling

## Goal
The goal of this phase is to ensure that all scripts in the `financial_db` project can be executed from **any directory** (e.g., project root, `scripts/` folder, or an unrelated folder) without encountering `FileNotFoundError` or `ModuleNotFoundError`. We will achieve this by replacing purely relative paths (like `"./data"`) with dynamic absolute paths using Python's `pathlib` module.

## Prerequisites
- Basic understanding of Python's `pathlib` module.
- Understanding of how `__file__` works in Python.
- Access to the `financial_db` codebase.

---

## Step 1: Create a Central Path Configuration

Instead of calculating paths in every single script, we will create a central utility to define the project structure.

1.  **Create a new file**: `db_utils/paths.py`.
2.  **Add the following code**:
    ```python
    import os
    from pathlib import Path

    # This determines the absolute path to the directory containing this file (db_utils/)
    # resolve() handles symlinks and makes it absolute.
    _DB_UTILS_DIR = Path(__file__).resolve().parent

    # The project root is one level up from db_utils/
    PROJECT_ROOT = _DB_UTILS_DIR.parent

    # Define other useful paths
    DATA_DIR = PROJECT_ROOT / "data"  # If exists
    DOC_DIR = PROJECT_ROOT / "doc"
    LOG_DIR = PROJECT_ROOT / "logs"
    SCRIPTS_DIR = PROJECT_ROOT / "scripts"
    NOTEBOOKS_DIR = PROJECT_ROOT / "notebooks"

    # Ensure directories exist (Optional quality of life improvement)
    # LOG_DIR.mkdir(exist_ok=True)
    ```

## Step 2: Refactor `scripts/clean_notebooks.py`

This script currently uses `glob.glob('**/*.ipynb')` which only looks relative to where you run the command.

1.  **Open** `scripts/clean_notebooks.py`.
2.  **Import the new path constants**. You might need to adjust `sys.path` if the package isn't installed in editable mode, but for now, rely on `sys.path` or ensure you are running as a module.
    *   *Junior Dev Note*: If you cannot import `db_utils` easily because of python path issues, you can explicitly add the project root to `sys.path` at the top of the script:
        ```python
        import sys
        from pathlib import Path
        
        # Add project root to python path to allow imports
        # This looks 2 levels up from scripts/clean_notebooks.py to find the root
        project_root = Path(__file__).resolve().parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        
        from db_utils.paths import PROJECT_ROOT, NOTEBOOKS_DIR
        ```
3.  **Update the `glob` call**:
    *   Change:
        ```python
        notebooks = glob.glob('**/*.ipynb', recursive=True)
        ```
    *   To:
        ```python
        # Use PROJECT_ROOT to anchor the search
        # We search specifically in the folders we expect, or recursively from ROOT
        notebooks = list(PROJECT_ROOT.rglob('*.ipynb'))
        ```
    *   *Note*: `rglob` returns `Path` objects, which are nicer to work with than strings.

4.  **Update file opening**:
    *   Ensure `clean_notebook` creates a valid path string if needed, mostly `open()` accepts Path objects in modern Python (3.6+).

## Step 3: Refactor `db_utils/db_setup.py`

This script currently does: `current_dir = Path(__file__).parent`. This is actually **good practice**! But we should standardize it to use our new system if applicable, or verify it works as intended.

1.  **Review** `db_utils/db_setup.py`.
2.  **Verify**: It uses `Path(__file__).parent` to locate `db_setup.sql`. This is robust.
3.  **Improvement**: We can verify the SQL file exists before trying to read it.
    ```python
    if not sql_path.exists():
        raise FileNotFoundError(f"SQL file not found at {sql_path}")
    ```

## Step 4: Audit Other Scripts for Hardcoded Paths

Scan the codebase for any `open(...)`, `pd.read_csv(...)`, or `path string` usage.

1.  **Search**: Use VS Code search for `open(`, `'/'`, `"/"` (common path separators).
2.  **Fix**: If you find something like `open("config.json")`, replace it.
    *   **Bad**: `open("config.json")` (Assumes CWD is where config.json is).
    *   **Good**:
        ```python
        from db_utils.paths import PROJECT_ROOT
        config_path = PROJECT_ROOT / "config.json"
        open(config_path)
        ```

## Step 5: Ensure Import Robustness (sys.path)

Often, scripts like `data_fetchers/shiller_cape.py` use absolute imports (`from data_fetchers.base_fetcher...`) which fail if you run the script from inside the `data_fetchers/` directory (because Python can't find the `data_fetchers` package in the current directory).

1.  **Standardize Script Entry Points**:
    *   For every script intended to be run directly (under `if __name__ == "__main__":`), add the project root to `sys.path` before imports if possible, or use a relative import hack.
    *   **Recommended approach**: Add this snippet to the top of scripts in `scripts/`, `data_fetchers/`, etc.:
    ```python
    import sys
    from pathlib import Path

    # Add project root to path so we can import packages like 'db_utils' or 'data_fetchers'
    # This logic assumes the script is 1 or 2 levels deep. Adjust .parent count accordingly.
    # For data_fetchers/shiller_cape.py (1 level deep from root):
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
        
    # Now you can safe import
    from db_utils.config import get_database_config
    ```

2.  **Apply to `data_fetchers/shiller_cape.py`**:
    *   It currently works if run from root.
    *   Try running it from `data_fetchers/`: It likely fails with `ModuleNotFoundError`.
    *   Apply the fix above.

## Step 6: Verify Implementation

To ensure robust path handling works:

1.  **Open Terminal**.
2.  **Navigate to a weird folder**: `cd /tmp` (or `cd ..`).
3.  **Run the script**: `python /path/to/financial_db/scripts/clean_notebooks.py`.
    *   It should **not** crash.
    *   It should find the notebooks in `financial_db` correctly.
4.  **Run from Root**: `cd /path/to/financial_db` -> `python scripts/clean_notebooks.py`.
    *   Should also work.
5.  **Test Imports**: Try running `cd data_fetchers && python shiller_cape.py ...` (expecting it to work now, or at least fail on args but not imports).

## Checklist - COMPLETED
- [x] `db_utils/paths.py` created with `PROJECT_ROOT` defined.
- [x] `scripts/clean_notebooks.py` refactored to use `PROJECT_ROOT` and `sys.path` fix.
- [x] `db_utils/db_setup.py` verified/refactored.
- [x] `data_fetchers/shiller_cape.py` updated with `sys.path` fix for robust execution.
- [x] `data_fetchers/stock_prices.py` updated with `sys.path` fix.
- [x] Confirmed no other hardcoded relative paths exist.
- [x] Tested running scripts from at least 3 different directories (Root, `scripts/`, Outside Repos).
