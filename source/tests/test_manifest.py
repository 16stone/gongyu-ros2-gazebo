import json,os,subprocess,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from gongyu import run
from gongyu.model import Event


class ManifestProvenance(unittest.TestCase):
    def test_revision_comes_from_loaded_source_not_invoking_directory(self):
        source=Path(run.__file__).resolve().parents[1]
        expected='fixture_source_revision'
        result=SimpleNamespace(events=[Event('unit_fixture','1',0,'referee','fixture',{})],metrics={'tasks':{}},trajectories=[],decisions=[],diagnostics=[])
        previous=Path.cwd()
        with tempfile.TemporaryDirectory() as temp:
            try:
                os.chdir(temp)
                with patch('gongyu.run.subprocess.check_output',side_effect=[expected+'\n','']) as git:
                    run.write_result(result,{'seed':0},'P3',Path(temp)/'output','unit_fixture')
                    self.assertTrue(all(c.kwargs['cwd']==source for c in git.call_args_list))
            finally:os.chdir(previous)
            manifest=json.loads((Path(temp)/'output/manifest.json').read_text())
        self.assertEqual(manifest['code_revision'],expected)

    def test_archived_source_without_git_keeps_unknown_revision_and_file_hashes(self):
        result=SimpleNamespace(events=[Event('archive','1',0,'referee','fixture',{})],metrics={'tasks':{}},trajectories=[],decisions=[],diagnostics=[])
        with tempfile.TemporaryDirectory() as temp:
            with patch('gongyu.run.subprocess.check_output',side_effect=FileNotFoundError('git')):
                run.write_result(result,{'seed':0},'P3',Path(temp)/'output','fixture')
            manifest=json.loads((Path(temp)/'output/manifest.json').read_text())
        self.assertEqual(manifest['code_revision'],'uncommitted')
        self.assertTrue(manifest['code_dirty']);self.assertIn('run.py',manifest['code_sha256'])


if __name__=='__main__':unittest.main()
