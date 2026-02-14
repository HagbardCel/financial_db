from db_utils.paths import DOC_DIR, DOCS_ROOT, PROJECT_ROOT, SUPPLEMENTAL_DOCS_DIR


def test_canonical_docs_root_points_to_doc_directory():
    assert DOCS_ROOT == PROJECT_ROOT / "doc"
    assert DOC_DIR == DOCS_ROOT


def test_supplemental_docs_root_points_to_docs_directory():
    assert SUPPLEMENTAL_DOCS_DIR == PROJECT_ROOT / "docs"
