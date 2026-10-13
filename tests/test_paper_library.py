import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


index = load_module("paper_index", REPO_ROOT / "library/scripts/build_paper_index.py")
sys.path.insert(0, str(REPO_ROOT / ".agents/skills/paper-extract/scripts"))
extract = load_module("paper_extract", REPO_ROOT / ".agents/skills/paper-extract/scripts/extract_pdf.py")


class PaperLibraryTests(unittest.TestCase):
    def setUp(self):
        scratch = REPO_ROOT / ".agent-tmp"
        scratch.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="test-paper-library-", dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.library = self.root / "library"
        self.papers = self.library / "papers"
        self.papers.mkdir(parents=True)

    def test_normalize_venue_keeps_unrelated_titles(self):
        aliases = json.loads(index.VENUE_ALIASES_PATH.read_text(encoding="utf-8"))
        self.assertEqual(index.normalize_venue("IEEE Transactions on Visualization and Computer Graphics 2026", aliases), "IEEE TVCG")
        self.assertEqual(index.normalize_venue("CHI (under review)", aliases), "CHI (under review)")
        self.assertEqual(index.normalize_venue("CHI Workshop on Example Topics", aliases), "CHI Workshop on Example Topics")

    def test_collect_and_render_legacy_records_and_supplements(self):
        record = self.papers / "2026 - Example"
        record.mkdir()
        (record / "paper.json").write_text(json.dumps({"title": "Original", "year": 2026, "venue": "IEEE Transactions on Visualization and Computer Graphics", "created": "2026-01-02T03:04:05+00:00", "supplements": [{"label": "Extra", "translation_path": "library/papers/2026 - Example/extra.md"}]}), encoding="utf-8")
        (record / "note.md").write_text('---\ntitle: "Example <script> & 研究"\nauthors: ["Example Author"]\n---\n', encoding="utf-8")
        (record / "extra.md").write_text("Example supplement", encoding="utf-8")
        with patch.multiple(index, REPO_ROOT=self.root, LIBRARY_ROOT=self.library, PAPERS_ROOT=self.papers):
            papers = index.collect_papers()
            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0]["venue"], "IEEE TVCG")
            self.assertEqual(papers[0]["added_at"], "2026-01-02T03:04:05+00:00")
            self.assertEqual(papers[0]["supplements"][0]["label"], "Extra")
            rows = index.render_rows(papers)
            self.assertIn("Example &lt;script&gt; &amp; 研究", rows)
            self.assertIn("extra.md", rows)
            self.assertIn('data-added="', rows)
            self.assertNotIn("<script>", rows)

    def test_added_at_survives_reextraction_and_legacy_created(self):
        record = self.papers / "2026 - Example"
        record.mkdir()
        kwargs = dict(out_dir=record, pdf_path=self.library / "pdf/2026 - Example.pdf", title="Example", metadata={}, manifest_path=record / "assets/manifest.json", pages_path=record / "assets/pages.json", fulltext_path=record / "fulltext.md")
        extract.write_paper_record(**kwargs)
        record_path = record / "paper.json"
        first = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertIsNotNone(datetime.fromisoformat(first["added_at"]).tzinfo)
        extract.write_paper_record(**kwargs)
        self.assertEqual(json.loads(record_path.read_text(encoding="utf-8"))["added_at"], first["added_at"])
        record_path.write_text(json.dumps({"created": "2025-12-01T00:00:00+00:00"}), encoding="utf-8")
        extract.write_paper_record(**kwargs)
        self.assertEqual(json.loads(record_path.read_text(encoding="utf-8"))["added_at"], "2025-12-01T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
