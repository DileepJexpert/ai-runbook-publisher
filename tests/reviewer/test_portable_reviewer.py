import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from reviewer.engine import FakeReviewEngine
from reviewer.git_snapshot import GitSnapshot, is_excluded
from reviewer.models import Finding, ReviewMode, ReviewResult
from reviewer.orchestrator import ReviewOrchestrator
from reviewer.validator import validate

class ReviewerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parents[2]); self.repo = Path(self.temp.name) / 'service'; self.repo.mkdir()
        for args in (['init'], ['config','user.email','test@example.com'], ['config','user.name','Test']): subprocess.run(['git','-C',str(self.repo),*args], check=True, capture_output=True)
        (self.repo/'app.txt').write_text('base'); subprocess.run(['git','-C',str(self.repo),'add','.'],check=True); subprocess.run(['git','-C',str(self.repo),'commit','-m','base'],check=True,capture_output=True)
        subprocess.run(['git','-C',str(self.repo),'checkout','-b','feature'],check=True,capture_output=True); (self.repo/'app.txt').write_text('change'); subprocess.run(['git','-C',str(self.repo),'commit','-am','change'],check=True,capture_output=True)
    def tearDown(self): self.temp.cleanup()
    def test_snapshot_and_both_modes(self):
        engine=FakeReviewEngine(); results=ReviewOrchestrator(engine).run(str(self.repo),'master','feature',ReviewMode.BOTH,Path(self.temp.name)/'out')
        self.assertEqual(set(results),{ReviewMode.BASELINE,ReviewMode.GUIDED}); self.assertEqual(engine.calls[0][1],engine.calls[1][1])
    def test_validator_and_exclusions(self):
        bad=Finding('x','unsupported','MAJOR'); existing=Finding('y','old','MINOR',evidence=[{'file':'a'}],introduced_by_pr=False)
        r=validate(ReviewResult(ReviewMode.BASELINE,[bad,existing])); self.assertEqual(r.findings,[]); self.assertEqual(len(r.pre_existing_observations),1); self.assertTrue(is_excluded('output/old/pr.diff'))
    def test_cli_help(self):
        result=subprocess.run([sys.executable,'reviewer_cli.py','--help'],cwd=Path(__file__).parents[2],text=True,capture_output=True)
        self.assertEqual(result.returncode,0); self.assertIn('--review-mode',result.stdout)
