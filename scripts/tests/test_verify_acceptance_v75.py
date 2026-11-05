"""Independent v75 evidence must bind required names and committed bytes."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

class IndependentVerifierTests(unittest.TestCase):
    def fixture(self, *, altered=False, optimized=False):
        with tempfile.TemporaryDirectory(prefix='mori-v75-verify-') as directory:
            root = Path(directory)
            (root / 'scripts').mkdir(); (root / 'm0/verifier/v75').mkdir(parents=True)
            script = root / 'scripts/verify_acceptance_v75.py'
            shutil.copyfile(ROOT / 'scripts/verify_acceptance_v75.py', script)
            names = json.loads((ROOT / 'm0/verifier/v75/expected-checks.json').read_text())
            (root / 'm0/verifier/v75/expected-checks.json').write_text(json.dumps(names))
            subprocess.run(['git','init','-q',str(root)],check=True)
            subprocess.run(['git','-C',str(root),'add','.'],check=True)
            subprocess.run(['git','-C',str(root),'-c','user.name=fixture','-c','user.email=fixture@example.test',
                            'commit','-qm','fixture'],check=True)
            sha = subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
            source = {}
            for path in (script, root / 'm0/verifier/v75/expected-checks.json'):
                source[str(path.relative_to(root))] = {'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                                                       'executable':bool(path.stat().st_mode & 0o111)}
            checks = [{'check':name,'passed':True} for name in names]
            if altered: checks[0]['check'] = 'forged_check'
            manifest_hash = digest(source)
            summary={'verifier_version':'v75','passed':True,'verifier_exit_code':0,'errors':[],'timed_out':False,
                'certificate_passed':True,'new_journal_passed':True,'source_history_unchanged':True,
                'execution_source_unchanged':True,'execution_source_manifest_sha256':manifest_hash,'elapsed_seconds':1,
                'source_binding':{'commit':sha,'matches_commit':True,'unchanged':True,'file_count':len(source),
                                  'source_manifest_sha256':manifest_hash}}
            certificate={'version':'v75','passed':True,'checks':checks,
                         'm7_configured_execution_evidence':{'certified':True}}
            artifact=root/'artifact';artifact.mkdir()
            for name,value in [('summary.json',summary),('LAST_RUN.json',certificate),('source-files.json',source),
                               ('execution-source-files.json',source)]:
                (artifact/name).write_text(json.dumps(value))
            (artifact/'new-runs.jsonl').write_text(json.dumps({'exit_code':0,'checks':checks,
                'command':'python3 verifier/v75/verify.py'})+'\n')
            command=[sys.executable] + (['-O'] if optimized else []) + [str(script),str(artifact),sha,'--output',str(root/'result.json')]
            return subprocess.run(command,capture_output=True,text=True).returncode

    def test_valid_exact_source_evidence_passes(self): self.assertEqual(self.fixture(),0)
    def test_replaced_required_check_is_rejected(self): self.assertNotEqual(self.fixture(altered=True),0)
    def test_optimized_interpreter_is_rejected(self): self.assertNotEqual(self.fixture(optimized=True),0)

if __name__ == '__main__': unittest.main()
