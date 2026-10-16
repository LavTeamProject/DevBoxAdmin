import json
import os
import tempfile
import unittest

import project_versions as pv


class Satisfies(unittest.TestCase):
    def test_ranges(self):
        cases = [("26.3.1", "20", False), ("26.3.1", "26", True), ("26.3.1", ">=18", True), ("26.3.1", "^20.1", False),
                 ("3.9.6", ">=3.9,<3.13", True), ("3.13.1", ">=3.9,<3.13", False), ("8.4.1", "^8.2", True), ("7.4.0", "^8.2", False),
                 ("20.11.0", "18.x || 20.x", True), ("20.11.0", "lts/*", None), ("1.22.5", "1.22", True), ("1.26.4", "1.22", False),
                 ("3.11.9", "~3.11", True), ("3.12.0", "~3.11", False), ("26", "latest", None), (None, "20", None)]
        for act, spec, exp in cases:
            self.assertEqual(pv.satisfies(act, spec), exp, (act, spec))

    def test_formula(self):
        self.assertEqual(pv.formula_for("node", "20.11.0"), "node@20")
        self.assertEqual(pv.formula_for("python", "3.12"), "python@3.12")
        self.assertEqual(pv.formula_for("java", "21.0.1-tem"), "openjdk@21")
        self.assertIsNone(pv.formula_for("node", "lts/*"))


class Requirements(unittest.TestCase):
    def test_files(self):
        with tempfile.TemporaryDirectory() as d:
            def w(n, t):
                with open(os.path.join(d, n), "w") as f:
                    f.write(t)
            w(".nvmrc", "v20.11.0\n")
            w("package.json", json.dumps({"engines": {"node": ">=18"}}))
            w("pyproject.toml", '[project]\nrequires-python = ">=3.10"\n')
            w("go.mod", "module x\n\ngo 1.22\n")
            w(".tool-versions", "ruby 3.3.0 # c\nnodejs 20\n")
            got = {(r["lang"], r["source"]): r["wanted"] for r in pv.requirements(d)}
            self.assertEqual(got[("node", ".nvmrc")], "v20.11.0")
            self.assertEqual(got[("node", "package.json")], ">=18")
            self.assertEqual(got[("python", "pyproject.toml")], ">=3.10")
            self.assertEqual(got[("go", "go.mod")], "1.22")
            self.assertEqual(got[("ruby", ".tool-versions")], "3.3.0")

    def test_symlink_escape_ignored(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as out:
            with open(os.path.join(out, "secret"), "w") as f:
                f.write("99")
            os.symlink(os.path.join(out, "secret"), os.path.join(d, ".nvmrc"))
            self.assertEqual(pv.requirements(d), [])


if __name__ == "__main__":
    unittest.main()
