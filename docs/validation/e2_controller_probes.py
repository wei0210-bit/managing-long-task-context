"""Root-owned P01-P05/P07 probes, isolated from executor test fixtures."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class CompletePackageProbes(unittest.TestCase):
    def setUp(self):
        self.source = Path(os.environ["MLTC_E2_PACKAGE"]).resolve()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / "package-a"
        shutil.copytree(self.source, self.package)

    def execute(self, arguments, *, loaded_package=None):
        return subprocess.run(
            [sys.executable, *arguments], cwd=self.root,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                 "PYTHONPATH": str((loaded_package or self.package) / "src")},
            capture_output=True, text=True, timeout=30)

    def verify(self):
        return self.execute([str(self.package / "scripts/skill_package.py"),
                             "verify", "--package", str(self.package)])

    def test_p01_complete_package_has_actual_five_entrypoints(self):
        verify = self.verify()
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
        doctor = self.execute([str(self.package / "scripts/context_doctor.py"),
                               "check", "--mode", "full", "--package-root", str(self.package)])
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        program = '''
import json,sys
from pathlib import Path
import managing_long_task_context as context
import managing_long_task_context.handoff as handoff
package=Path(sys.argv[1])
names=('prepare_handoff','validate_handoff','activate_handoff','cancel_handoff','handoff_status')
assert all(callable(getattr(context,n)) and n in context.__all__ for n in names)
assert Path(context.__file__).is_relative_to(package)
assert Path(handoff.__file__).is_relative_to(package)
result=context.runtime_identity(package_root=package)
print(json.dumps(result))
'''
        result = self.execute(["-c", program, str(self.package)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        identity = json.loads(result.stdout)
        self.assertEqual(identity["status"], "pass", identity)
        self.assertEqual(identity["identity"]["skill_version"], "0.8.0")

    def test_p02_real_content_tamper_fails_full_verification(self):
        path = self.package / "src/managing_long_task_context/handoff.py"
        path.write_bytes(path.read_bytes() + b"\n# root adversarial content mutation\n")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(json.loads(result.stdout)["status"], "fail")

    def test_p03_missing_module_fails_full_verification(self):
        (self.package / "src/managing_long_task_context/handoff.py").unlink()
        result = self.verify()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(json.loads(result.stdout)["status"], "fail")

    def test_p04_runtime_cannot_borrow_other_package_root(self):
        other = self.root / "package-b"
        shutil.copytree(self.package, other)
        program = "import json,sys; import managing_long_task_context as c; print(json.dumps(c.runtime_identity(package_root=sys.argv[1])))"
        result = self.execute(["-c", program, str(other)])
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertNotEqual(report["status"], "pass", report)
        self.assertIn("RUNTIME_PATH_MISMATCH", report["codes"])

    def test_p05_loaded_process_cannot_adopt_replaced_manifest(self):
        program = '''
import json,sys
from pathlib import Path
import managing_long_task_context as context
package=Path(sys.argv[1]); path=package/'skill-manifest.json'
before=context.runtime_identity(package_root=package)
manifest=json.loads(path.read_text()); manifest['source_revision']='candidate:replacement'
path.write_text(json.dumps(manifest))
after=context.runtime_identity(package_root=package)
print(json.dumps({'before':before,'after':after}))
'''
        result = self.execute(["-c", program, str(self.package)])
        self.assertEqual(result.returncode, 0, result.stderr)
        reports = json.loads(result.stdout)
        self.assertEqual(reports["before"]["status"], "pass")
        self.assertNotEqual(reports["after"]["status"], "pass", reports)
        self.assertIn("PACKAGE_IDENTITY_MISMATCH", reports["after"]["codes"])

    def test_p07_only_handoff_loaded_outside_package_is_detected(self):
        outside = self.root / "outside-handoff.py"
        shutil.copy2(self.package / "src/managing_long_task_context/handoff.py", outside)
        program = '''
import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('managing_long_task_context.handoff',sys.argv[2])
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)
import managing_long_task_context as context
print(json.dumps(context.runtime_identity(package_root=sys.argv[1])))
'''
        result = self.execute(["-c", program, str(self.package), str(outside)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertNotEqual(report["status"], "pass", report)
        self.assertIn("RUNTIME_PATH_MISMATCH", report["codes"])


if __name__ == "__main__":
    unittest.main()
