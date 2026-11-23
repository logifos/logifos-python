"""Qualify a built wheel and its installed runtime outside the source tree.

Run with the target environment's Python, using -I and an external working
directory: python -I /checkout/tests/test_distribution.py /path/to/logifos.whl
"""

import base64
import csv
from email.parser import BytesParser
import hashlib
from importlib import metadata
import io
from pathlib import Path
import sys
import unittest
import zipfile


VERSION = "0.1.0"
DIST_INFO = "logifos-{}.dist-info/".format(VERSION)
LICENSE_SHA256 = "2d0f8a412f45f64d0e2bba4f9592907371613f219fe01f2e7a88c0381a672d07"
WHEEL_PATH = None


class DistributionSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wheel = zipfile.ZipFile(WHEEL_PATH)
        cls.addClassCleanup(cls.wheel.close)
        cls.names = cls.wheel.namelist()

    def test_wheel_contains_only_runtime_and_distribution_metadata(self):
        self.assertEqual(len(self.names), len(set(self.names)), "duplicate wheel paths")
        licenses = [name for name in self.names if name in (
            DIST_INFO + "LICENSE.txt", DIST_INFO + "licenses/LICENSE.txt"
        )]
        self.assertEqual(len(licenses), 1, "wheel must carry the MIT notice")
        expected = {"logifos/__init__.py", "logifos/_runtime.py", licenses[0]}
        expected.update(DIST_INFO + name for name in (
            "METADATA", "WHEEL", "top_level.txt", "RECORD"
        ))
        self.assertEqual(set(self.names), expected)
        self.assertEqual(hashlib.sha256(self.wheel.read(licenses[0])).hexdigest(),
                         LICENSE_SHA256)

    def test_wheel_metadata_preserves_package_contract(self):
        info = BytesParser().parsebytes(self.wheel.read(DIST_INFO + "METADATA"))
        self.assertEqual(info["Name"], "logifos")
        self.assertEqual(info["Version"], VERSION)
        self.assertEqual(info["Requires-Python"], ">=3.9")
        self.assertEqual(info["License"], "MIT")
        wheel = BytesParser().parsebytes(self.wheel.read(DIST_INFO + "WHEEL"))
        self.assertEqual(wheel["Root-Is-Purelib"], "true")
        self.assertEqual(wheel["Tag"], "py3-none-any")

    def test_record_covers_every_file_with_matching_hashes_and_sizes(self):
        record = DIST_INFO + "RECORD"
        rows = list(csv.reader(io.StringIO(self.wheel.read(record).decode("utf-8"))))
        self.assertEqual(len(rows), len(self.names))
        self.assertEqual({row[0] for row in rows}, set(self.names))
        for name, digest, size in rows:
            with self.subTest(path=name):
                if name == record:
                    self.assertEqual((digest, size), ("", ""))
                    continue
                data = self.wheel.read(name)
                expected = base64.urlsafe_b64encode(hashlib.sha256(data).digest())
                self.assertEqual(digest, "sha256=" + expected.rstrip(b"=").decode("ascii"))
                self.assertEqual(size, str(len(data)))

    def test_import_uses_the_installed_distribution_outside_checkout(self):
        import logifos

        checkout = Path(__file__).resolve().parents[1]
        self.assertNotIn(checkout, (Path.cwd().resolve(), *Path.cwd().resolve().parents))
        imported = Path(logifos.__file__).resolve()
        self.assertNotIn(checkout, (imported, *imported.parents))
        self.assertEqual(metadata.version("logifos"), VERSION)
        distribution = metadata.distribution("logifos")
        self.assertEqual(imported, Path(distribution.locate_file("logifos/__init__.py")).resolve())
        for name in ("__init__.py", "_runtime.py"):
            installed = distribution.locate_file("logifos/" + name)
            self.assertEqual(installed.read_bytes(), self.wheel.read("logifos/" + name))
        installed_licenses = [file for file in distribution.files
                              if str(file).endswith("/LICENSE.txt")]
        self.assertEqual(len(installed_licenses), 1)
        self.assertEqual(hashlib.sha256(distribution.locate_file(installed_licenses[0]).read_bytes()).hexdigest(),
                         LICENSE_SHA256)

    def test_installed_explicit_library_selection_refuses_missing_library(self):
        import logifos

        for fmt in (None, "svg", "png"):
            with self.subTest(format=fmt):
                options = {} if fmt is None else {"fmt": fmt}
                with self.assertRaises(logifos.NativeLibraryError):
                    logifos.render({}, library_path="", **options)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -I test_distribution.py /path/to/logifos.whl")
    WHEEL_PATH = Path(sys.argv.pop()).resolve(strict=True)
    unittest.main(verbosity=2)
