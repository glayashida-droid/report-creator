# Leg-scoped test dirs — change scope

Use this list when splitting commits/PRs. **In scope** = ADR-0002 / `docs/specs/leg-scoped-test-dirs.md`.

## In scope (leg-scoped)

| Area | Files |
|------|--------|
| IO seam | `src/io/test_photos.py`, `src/io/data_tables.py` (path/retarget/hook only) |
| State | `src/models/project_state.py` — `duplicate_test_names`, per-leg uniqueness, `DUPLICATE_TEST_NAME_MESSAGE` |
| UI | `src/ui/leg_graph.py`, `src/ui/test_photos_panel.py` (hook guards), `src/ui/main_window.py` (`save_state` dup gate), `src/ui/test_detail_dialog.py` (`_on_add_data_table` dup gate) |
| Export | `src/generators/word_engine.py`, `src/generators/photo_scraper.py` |
| Tests | `tests/test_test_photos.py`, `tests/test_data_tables.py`, `tests/test_project_state.py`, `tests/test_leg_graph.py` |
| Docs | `docs/specs/leg-scoped-test-dirs.md`, `docs/adr/0002-leg-scoped-test-dirs.md`, `CONTEXT.md`, `SPEC.md`, `docs/adr/0001-photos-live-on-disk.md`, `docs/specs/data-tables.md` |

## Out of scope (bundle separately)

| Feature | Files |
|---------|--------|
| Network / SMB | `src/io/network_sources.py`, `tests/test_network_sources.py` |
| Application ingest / parser | `application_parser/*`, `src/application_ingest.py`, `src/parsers/pdf_parser.py` |
| Sample columns / files | `src/sample_columns.py`, `src/io/sample_files.py`, related tests |
| Custom overview / multi-sample | portions of `src/models/project_state.py`, `src/ui/main_window.py`, `src/ui/test_detail_dialog.py` |
| Theme / template | `src/ui/theme.py`, `templates/template_ze.docx` |
| Misc | `tests/test_equipment_expiry.py`, `tests/test_sample_result_desc.py`, `idea.md`, `run.command`, `scripts/` |

Mixed files (`project_state.py`, `main_window.py`, `test_detail_dialog.py`) need manual hunks if split mechanically.
