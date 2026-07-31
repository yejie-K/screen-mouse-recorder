from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.ocr_runtime import load_rapidocr


class _Engine:
    name = "rapidocr-test"
    version = "1.0"


class OCRRuntimeTests(unittest.TestCase):
    def test_discovers_development_runtime(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            site_packages = root / "experiments" / "ocr_engine_eval_20260709" / ".venv" / "Lib" / "site-packages"
            (site_packages / "rapidocr_onnxruntime").mkdir(parents=True)
            with patch("tools.ocr_runtime.find_spec", return_value=None):
                result = load_rapidocr(root, engine_factory=_Engine)
            self.assertTrue(result.available)
            self.assertEqual(result.source, "development")
            self.assertIsInstance(result.engine, _Engine)
            self.assertIn(str(site_packages), sys.path)

    def test_explicit_runtime_takes_priority_over_bundled_candidates(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            explicit = root / "custom_ocr"
            explicit_site = explicit / "Lib" / "site-packages"
            explicit_site.mkdir(parents=True)
            (root / ".runtime" / "ocr" / "Lib" / "site-packages" / "rapidocr_onnxruntime").mkdir(parents=True)
            with patch("tools.ocr_runtime.find_spec", return_value=None):
                result = load_rapidocr(root, engine_factory=_Engine, explicit_runtime=explicit)
            self.assertTrue(result.available)
            self.assertEqual(result.source, "explicit")
            self.assertEqual(sys.path[0], str(explicit_site))

    def test_missing_runtime_returns_a_nonfatal_status(self):
        with TemporaryDirectory() as directory:
            with patch("tools.ocr_runtime.find_spec", return_value=None):
                result = load_rapidocr(Path(directory), engine_factory=_Engine)
            self.assertFalse(result.available)
            self.assertIsNone(result.engine)
            self.assertEqual(result.source, "missing")
            self.assertIn("暂不可用", result.message)


if __name__ == "__main__":
    unittest.main()
