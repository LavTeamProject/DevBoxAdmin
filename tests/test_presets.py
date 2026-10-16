"""Пресеты проекта: виды команд и подсказки по файлам проекта (только чтение файлов)."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import projects  # noqa: E402
import runs  # noqa: E402


class Suggest(unittest.TestCase):
    def _proj(self, files):
        d = tempfile.mkdtemp()
        for name, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(d, name)) or d, exist_ok=True)
            with open(os.path.join(d, name), "w") as f:
                f.write(text)
        return os.path.realpath(d)

    def suggest(self, files):
        d = self._proj(files)
        with mock.patch.object(projects, "resolve", return_value=d):
            return projects.preset_suggest({"path": d})["suggest"]

    def test_node_pnpm_scripts(self):
        s = self.suggest({"package.json": json.dumps({"scripts": {"lint": "eslint .", "test": "vitest", "build": "vite build", "dev": "vite"}}),
                          "pnpm-lock.yaml": ""})
        self.assertEqual(s, {"install": "pnpm install", "lint": "pnpm run lint", "test": "pnpm test", "build": "pnpm run build", "dev": "pnpm run dev"})

    def test_npm_ci_with_lock_and_start_as_dev(self):
        s = self.suggest({"package.json": json.dumps({"scripts": {"start": "node index.js"}}), "package-lock.json": "{}"})
        self.assertEqual(s["install"], "npm ci")
        self.assertEqual(s["dev"], "npm run start")
        self.assertNotIn("test", s)

    def test_python_go_rust_flutter_php(self):
        self.assertEqual(self.suggest({"requirements.txt": "x"})["install"], "pip3 install -r requirements.txt")
        self.assertEqual(self.suggest({"uv.lock": ""})["install"], "uv sync")
        self.assertEqual(self.suggest({"go.mod": "module x"})["test"], "go test ./...")
        self.assertEqual(self.suggest({"Cargo.toml": ""})["lint"], "cargo clippy")
        self.assertEqual(self.suggest({"pubspec.yaml": ""})["install"], "flutter pub get")
        s = self.suggest({"composer.json": "{}", "artisan": ""})
        self.assertEqual((s["install"], s["dev"]), ("composer install", "php artisan serve"))

    def test_unrecognised_project_gives_nothing(self):
        self.assertEqual(self.suggest({"README.md": "hi"}), {})


class Kinds(unittest.TestCase):
    def test_preset_kinds_and_run_kinds(self):
        self.assertEqual(projects.PRESET_KINDS, ("install", "lint", "test", "build", "dev"))
        self.assertIn("install", runs.KINDS)
        self.assertNotIn("dev", runs.KINDS)         # dev — без лимита времени, отдельный вид

    def test_presets_get_has_all_kinds(self):
        with mock.patch.object(projects, "_read_registry_file", return_value={"presets": {}}):
            self.assertEqual(set(projects.presets_get("/x")), {"editor", *projects.PRESET_KINDS})


if __name__ == "__main__":
    unittest.main()
