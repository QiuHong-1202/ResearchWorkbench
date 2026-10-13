import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fetch_arxiv", REPO_ROOT / ".agents/skills/arxiv-daily/scripts/fetch_arxiv.py")
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)


class ArxivMonthlyTests(unittest.TestCase):
    def test_recovery_finds_recommendation_in_announcement_month(self):
        scratch = REPO_ROOT / ".agent-tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="test-arxiv-monthly-", dir=scratch) as name:
            root = Path(name)
            date = "2026-09-30"
            date_dir = root / "artifacts" / date
            date_dir.mkdir(parents=True)
            manifest_path = date_dir / f"{date}-manifest.json"
            recommendation = root / "recommendations" / "2026-09" / f"{date}-arxiv-recommended.md"
            recommendation.parent.mkdir(parents=True)
            recommendation.write_text("Example old recommendation", encoding="utf-8")
            config = root / "config.yaml"
            for relative in (False, True):
                with self.subTest(relative=relative):
                    recommendations_root = recommendation.parent.parent
                    if relative:
                        recommendations_root = recommendations_root.relative_to(REPO_ROOT)
                    config.write_text(f"categories: [cs.CV]\nrecommendations_root: {recommendations_root.as_posix()}\n", encoding="utf-8")
                    manifest_path.write_text(json.dumps({"status": "partial", "categories": []}), encoding="utf-8")
                    args = ["fetch_arxiv.py", "--date", date, "--category", "cs.LG", "--config", str(config), "--out-dir", str(root / "artifacts")]
                    with patch.object(sys, "argv", args), patch.object(fetch, "process_category", return_value={"category": "cs.LG", "status": "skipped"}) as process:
                        self.assertEqual(fetch.main(), 0)
                    self.assertEqual(process.call_args.args[0], "cs.LG")
                    self.assertEqual(process.call_args.kwargs["source"], "api")
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    self.assertEqual(manifest["status"], "ok")
                    self.assertTrue(any(str(recommendation) in warning and "--force" in warning for warning in manifest["warnings"]))
                    self.assertEqual(recommendation.read_text(encoding="utf-8"), "Example old recommendation")


if __name__ == "__main__":
    unittest.main()
