"""Цикл «тест → исправление → тест» для агента: настоящий код выхода, отмена убивает процесс, красные тесты не эскалируются, окружение запуска."""
import os
import subprocess
import tempfile
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import core  # noqa: E402
import plans  # noqa: E402


def _wait(job_id, limit=10):
    t0 = time.time()
    while not core.JOBS[job_id]["done"] and time.time() - t0 < limit:
        time.sleep(0.05)
    return core.JOBS[job_id]


class Steps(unittest.TestCase):
    def test_step_failed_keeps_real_exit_code(self):
        def step(log):
            raise core.StepFailed(3)
        j = _wait(core.start_steps("t", [("x", step, {})], "test-rc"))
        self.assertEqual(j["code"], 3)

    def test_command_step_exit_code(self):
        j = _wait(core.start_steps("t", [("x", ["/bin/sh", "-c", "exit 5"], {})], "test-rc2"))
        self.assertEqual(j["code"], 5)

    def test_cancel_kills_attached_process(self):
        holder = {}

        def step(log):
            p = subprocess.Popen(["/bin/sleep", "30"], start_new_session=True)
            holder["p"] = p
            log.attach(p)
            if p.wait() != 0:
                raise core.StepFailed(p.returncode)
        jid = core.start_steps("t", [("sleep", step, {})], "test-cancel")
        t0 = time.time()
        while "p" not in holder and time.time() - t0 < 5:
            time.sleep(0.05)
        core.cancel_job({"id": jid})
        j = _wait(jid)
        self.assertTrue(j["done"])
        self.assertEqual(j["code"], 143)
        self.assertIsNotNone(holder["p"].poll())       # процесс действительно остановлен
        self.assertNotIn("_proc", j)


class RedRun(unittest.TestCase):
    def _plan(self, code, op="project.run"):
        jid = "j-red-%s-%s" % (op, code)
        core.JOBS[jid] = {"id": jid, "done": True, "code": code, "lines": [], "kind": "x", "started": 0}
        return {"operation": op, "status": "executing", "job": jid, "executed_at": time.time(), "expires": time.time() + 99}

    def test_failed_tests_are_not_escalation(self):
        self.assertTrue(plans._red_run(self._plan(1)))
        for c in (124, 127, 143, -1):                  # таймаут, «не запустилось», отмена — считаются
            self.assertFalse(plans._red_run(self._plan(c)), c)
        self.assertFalse(plans._red_run(self._plan(1, "package.install")))


class NamesAndPaths(unittest.TestCase):
    def test_local_archives_refused(self):
        import runtimes
        for name in ("evil.tgz", "x.tar.gz", "pkg.gem", "a.zip"):
            self.assertTrue(runtimes.LOCAL_ARCHIVE_RE.search(name), name)
        for name in ("typescript", "@vue/cli", "eslint@9.1.0"):
            self.assertTrue(runtimes.NPM_RE.match(name) and not runtimes.LOCAL_ARCHIVE_RE.search(name), name)


class ProjectEnv(unittest.TestCase):
    def test_shims_first_and_panel_env(self):
        with mock.patch.object(core, "run", return_value=(0, "noise\n__PATH__/opt/x/bin:node_modules/.bin:.:/usr/bin\n", "")), \
             mock.patch.object(core, "load_state", return_value={"env": {"java": {"JAVA_HOME": "/jdk/Home"}}}):
            env = core.project_env()
        parts = env["PATH"].split(":")
        self.assertEqual(parts[0], core.SHIM_DIR)
        self.assertEqual(parts[1], "/jdk/Home/bin")
        self.assertIn("/opt/x/bin", parts)
        self.assertEqual(env["JAVA_HOME"], "/jdk/Home")
        self.assertEqual(len(parts), len(set(parts)))   # без повторов
        self.assertTrue(all(os.path.isabs(x) for x in parts))   # относительные пути (node_modules/.bin, «.») отброшены


if __name__ == "__main__":
    unittest.main()


class EarlyCancelAndOrphan(unittest.TestCase):
    def test_cancel_before_process_start_runs_nothing(self):
        import runs
        with tempfile.TemporaryDirectory() as d, mock.patch.object(runs, "RUNS_DIR", d), mock.patch.object(runs, "project_env", return_value={}), \
             mock.patch.object(runs, "_record"), mock.patch.object(runs.subprocess, "Popen", side_effect=AssertionError("must not start")):
            step = runs._runner("r000001", d, "test", "npm test", ["npm", "test"], {})
            log = lambda line: None  # noqa: E731
            log.cancelled = lambda: True
            with self.assertRaises(core.StepFailed) as cm:
                step(log)
        self.assertEqual(cm.exception.rc, 143)

    def test_dev_orphan_found_by_pidfile_and_stopped(self):
        import runs
        with tempfile.TemporaryDirectory() as d, mock.patch.object(runs, "RUNS_DIR", d):
            p = subprocess.Popen(["/bin/sleep", "30"], start_new_session=True)
            try:
                runs._dev_pidfile("/proj", p.pid, "/bin/sleep")
                self.assertEqual(runs._dev_orphan("/proj"), p.pid)
                runs._dev_pidfile("/proj", p.pid, "node")              # чужая команда под тем же pid — не «наш» сервер
                self.assertIsNone(runs._dev_orphan("/proj"))
                runs._dev_pidfile("/proj", p.pid, "/bin/sleep")
                with mock.patch.object(runs.projects, "resolve", return_value="/proj"):
                    self.assertEqual(runs.dev_stop({"project": "/proj"}), {"ok": True})
                self.assertIsNotNone(p.wait(timeout=5))
                self.assertIsNone(runs._dev_orphan("/proj"))
            finally:
                if p.poll() is None:
                    p.kill()
