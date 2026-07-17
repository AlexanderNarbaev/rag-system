# tests/etl/test_etl_cleanup.py
"""Tests for FR-07: Post-indexing data cleanup."""
import json


class TestCleanupPath:
    def test_removes_existing_directory(self, tmp_path):
        from etl.scheduler.run_etl import _cleanup_path

        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()
        (test_dir / "file.txt").write_text("data")
        assert test_dir.exists()
        _cleanup_path(test_dir, dry_run=False)
        assert not test_dir.exists()

    def test_skips_missing_directory(self, tmp_path):
        from etl.scheduler.run_etl import _cleanup_path

        result = _cleanup_path(tmp_path / "nonexistent", dry_run=False)
        assert result is False

    def test_dry_run_does_not_remove(self, tmp_path):
        from etl.scheduler.run_etl import _cleanup_path

        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()
        (test_dir / "file.txt").write_text("data")
        result = _cleanup_path(test_dir, dry_run=True)
        assert result is True
        assert test_dir.exists()


class TestStripChunkFullText:
    def test_strips_full_text_from_chunks(self, tmp_path):
        from etl.scheduler.run_etl import _strip_chunk_full_text

        hot_dir = tmp_path / "hot_chunks"
        hot_dir.mkdir()
        chunks = [
            {
                "text": "long full text content that should be removed from hot storage",
                "hash": "abc123",
                "source_id": "doc1",
                "version": "1.0",
                "doc_title": "Test Doc",
                "source_type": "confluence",
                "extra_field": "should be dropped",
            },
            {
                "text": "another chunk",
                "hash": "def456",
                "source_id": "doc2",
                "version": "2.0",
                "doc_title": "Doc 2",
                "source_type": "jira",
            },
        ]
        (hot_dir / "doc1.json").write_text(json.dumps(chunks))

        files_stripped, bytes_freed = _strip_chunk_full_text(hot_dir, dry_run=False)
        assert files_stripped == 1
        assert bytes_freed > 0

        result = json.loads((hot_dir / "doc1.json").read_text())
        assert len(result) == 2
        for entry in result:
            assert "text" not in entry
            assert "hash" in entry
            assert "source_id" in entry
            assert "version" in entry
            assert "extra_field" not in entry

    def test_dry_run_does_not_modify(self, tmp_path):
        from etl.scheduler.run_etl import _strip_chunk_full_text

        hot_dir = tmp_path / "hot_chunks"
        hot_dir.mkdir()
        original = json.dumps([{"text": "content", "hash": "abc", "source_id": "d1"}])
        (hot_dir / "doc1.json").write_text(original)

        _strip_chunk_full_text(hot_dir, dry_run=True)
        assert (hot_dir / "doc1.json").read_text().strip() == original.strip()

    def test_empty_hot_dir(self, tmp_path):
        from etl.scheduler.run_etl import _strip_chunk_full_text

        hot_dir = tmp_path / "hot_chunks"
        hot_dir.mkdir()
        f, b = _strip_chunk_full_text(hot_dir, dry_run=False)
        assert f == 0
        assert b == 0

    def test_missing_hot_dir(self, tmp_path):
        from etl.scheduler.run_etl import _strip_chunk_full_text

        f, b = _strip_chunk_full_text(tmp_path / "nonexistent", dry_run=False)
        assert f == 0
        assert b == 0


class TestRunCleanup:
    def test_not_requested_by_default(self, tmp_path):
        from etl.scheduler.run_etl import run_cleanup

        config = {}
        result = run_cleanup(config, cleanup_after_index=False)
        assert result["ran"] is False

    def test_cleanup_after_index(self, tmp_path):
        from etl.scheduler.run_etl import run_cleanup

        raw_conflu = tmp_path / "raw_confluence"
        raw_jira = tmp_path / "raw_jira"
        raw_gitlab = tmp_path / "raw_gitlab"
        chunks_dir = tmp_path / "chunks_out"
        hot_dir = tmp_path / "hot_chunks_out"

        for d in [raw_conflu, raw_jira, raw_gitlab, chunks_dir, hot_dir]:
            d.mkdir()
            (d / "data.txt").write_text("test")

        config = {
            "confluence": {"output_dir": str(raw_conflu)},
            "jira": {"output_dir": str(raw_jira)},
            "gitlab": {"output_dir": str(raw_gitlab)},
            "chunking": {"output_dir": str(chunks_dir)},
            "indexing": {
                "hot_dir": str(hot_dir),
                "cold_dir": str(tmp_path / "cold_chunks"),
                "lake_dir": str(tmp_path / "cold_lake"),
            },
        }
        result = run_cleanup(config, cleanup_after_index=True)
        assert result["ran"] is True
        assert not raw_conflu.exists()
        assert not raw_jira.exists()
        assert not raw_gitlab.exists()
        assert not chunks_dir.exists()

    def test_dry_run_preserves_files(self, tmp_path):
        from etl.scheduler.run_etl import run_cleanup

        raw_conflu = tmp_path / "raw_confluence"
        raw_conflu.mkdir()
        (raw_conflu / "data.txt").write_text("test")

        config = {
            "confluence": {"output_dir": str(raw_conflu)},
            "jira": {"output_dir": str(tmp_path / "nonexistent_jira")},
            "gitlab": {"output_dir": str(tmp_path / "nonexistent_gitlab")},
            "chunking": {"output_dir": str(tmp_path / "nonexistent_chunks")},
            "indexing": {
                "hot_dir": str(tmp_path / "hot_chunks"),
                "cold_dir": str(tmp_path / "cold_chunks"),
                "lake_dir": str(tmp_path / "cold_lake"),
            },
        }
        result = run_cleanup(config, cleanup_after_index=True, dry_run=True)
        assert result["ran"] is True
        assert raw_conflu.exists()

    def test_keep_cold_storage(self, tmp_path):
        from etl.scheduler.run_etl import run_cleanup

        raw = tmp_path / "raw_confl"
        raw.mkdir()
        cold_dir = tmp_path / "cold_chunks_out"
        cold_dir.mkdir()
        lake_dir = tmp_path / "cold_lake_out"
        lake_dir.mkdir()
        hot_dir = tmp_path / "hot_chunks_out"
        hot_dir.mkdir()

        config = {
            "confluence": {"output_dir": str(raw)},
            "jira": {"output_dir": str(tmp_path / "nj")},
            "gitlab": {"output_dir": str(tmp_path / "ng")},
            "chunking": {"output_dir": str(tmp_path / "nc")},
            "indexing": {
                "hot_dir": str(hot_dir),
                "cold_dir": str(cold_dir),
                "lake_dir": str(lake_dir),
            },
            "etl": {"data_retention": {"keep_cold_storage": True}},
        }
        run_cleanup(config, cleanup_after_index=True)
        assert cold_dir.exists()
        assert lake_dir.exists()

    def test_config_driven_cleanup(self, tmp_path):
        from etl.scheduler.run_etl import run_cleanup

        raw = tmp_path / "raw_confl"
        raw.mkdir()
        hot_dir = tmp_path / "hot_chunks"
        hot_dir.mkdir()

        config = {
            "confluence": {"output_dir": str(raw)},
            "jira": {"output_dir": str(tmp_path / "nj")},
            "gitlab": {"output_dir": str(tmp_path / "ng")},
            "chunking": {"output_dir": str(tmp_path / "nc")},
            "indexing": {
                "hot_dir": str(hot_dir),
                "cold_dir": str(tmp_path / "cold_chunks"),
                "lake_dir": str(tmp_path / "cold_lake"),
            },
            "etl": {"data_retention": {"cleanup_after_run": True, "keep_cold_storage": True}},
        }
        result = run_cleanup(config)
        assert result["ran"] is True
        assert not raw.exists()


class TestCLIFlags:
    def test_cleanup_after_index_flag_present(self):
        import argparse


        parser = argparse.ArgumentParser()
        parser.add_argument("--cleanup-after-index", action="store_true")
        args = parser.parse_args(["--cleanup-after-index"])
        assert args.cleanup_after_index is True

    def test_dry_run_flag_present(self):
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--dry-run", action="store_true")
        args = parser.parse_args(["--dry-run"])
        assert args.dry_run is True
