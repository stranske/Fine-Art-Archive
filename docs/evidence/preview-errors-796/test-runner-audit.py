"""Regression checks for evidence validation; no production mutation is performed."""

import importlib.util
import pathlib
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("fault_runner", HERE / "run-faults.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
NODE = runner.base + "test_preview_rejects_invalid_render_options_before_rendering"


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.red = pathlib.Path(self.temp.name) / "red.xml"
        self.green = pathlib.Path(self.temp.name) / "green.xml"
        self.red.write_bytes((HERE / "invalid-target-red.xml").read_bytes())
        self.green.write_bytes((HERE / "invalid-target-green.xml").read_bytes())

    def validate(self, count=1):
        return runner.validate_reports(self.red, self.green, NODE, "query0", count)

    def change(self, path, edit):
        tree = ET.parse(path)
        edit(tree.getroot())
        tree.write(path)

    def test_real_assertion_audit_is_retained(self):
        audit = self.validate()
        self.assertEqual(audit["observed_failures"], 1)
        self.assertTrue(audit["assertion_failure_messages"][0].startswith("assert "))

    def test_setup_error_rejected(self):
        self.change(self.red, lambda root: ET.SubElement(next(root.iter("testcase")), "error"))
        with self.assertRaisesRegex(AssertionError, "collection/setup error"):
            self.validate()

    def test_non_assertion_failure_rejected(self):
        self.change(
            self.red, lambda root: next(root.iter("failure")).set("message", "RuntimeError: broken")
        )
        with self.assertRaisesRegex(AssertionError, "non-assertion failure"):
            self.validate()

    def test_missing_case_rejected(self):
        with self.assertRaisesRegex(AssertionError, "unexpected case count"):
            self.validate(count=2)

    def test_wrong_test_rejected(self):
        self.change(
            self.red, lambda root: next(root.iter("testcase")).set("name", "test_unrelated")
        )
        with self.assertRaisesRegex(AssertionError, "wrong test"):
            self.validate()

    def test_wrong_parameter_rejected(self):
        self.change(
            self.green,
            lambda root: next(root.iter("testcase")).set(
                "name", NODE.split("::")[1] + "[query1-wrong]"
            ),
        )
        with self.assertRaisesRegex(AssertionError, "wrong parameter selection"):
            self.validate()

    def test_skipped_green_rejected(self):
        self.change(self.green, lambda root: ET.SubElement(next(root.iter("testcase")), "skipped"))
        with self.assertRaisesRegex(AssertionError, "selected case skipped"):
            self.validate()

    def test_failed_green_rejected(self):
        self.change(self.green, lambda root: ET.SubElement(next(root.iter("testcase")), "failure"))
        with self.assertRaisesRegex(AssertionError, "restored test failed"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
