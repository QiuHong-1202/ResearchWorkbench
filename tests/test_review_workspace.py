import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("review_workspace", REPO_ROOT / ".agents/skills/review-workspace/scripts/workspace.py")
workspace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workspace)


class ReviewWorkspaceTests(unittest.TestCase):
    def setUp(self):
        scratch = REPO_ROOT / ".agent-tmp"
        scratch.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="test-review-workspace-", dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / "workspace.local.json"

    def test_resolve_existing_workspace_without_writing_to_it(self):
        review_dir = self.root / "Example Review 研究"
        review_dir.mkdir()
        self.config.write_text(json.dumps({"REVIEW_WORKSPACE": str(review_dir)}, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(workspace.resolve_workspace(self.config), review_dir.resolve())
        self.assertEqual(list(review_dir.iterdir()), [])

    def test_invalid_configuration_does_not_create_workspace(self):
        missing = self.root / "missing"
        for value in ("", "relative/path", str(missing)):
            with self.subTest(value=value):
                self.config.write_text(json.dumps({"REVIEW_WORKSPACE": value}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    workspace.resolve_workspace(self.config)
                self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
