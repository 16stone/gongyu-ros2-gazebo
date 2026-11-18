import json
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock,patch

from ros.run_nav_calibration import run


class NavRunner(TestCase):
    def test_client_timeout_records_failure_and_closes_owned_stack(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'episode'
            process=Mock(pid=123456,returncode=0)
            with patch('ros.run_nav_calibration.subprocess.Popen',return_value=process), \
                 patch('ros.run_nav_calibration.subprocess.run',side_effect=subprocess.TimeoutExpired('client',300)), \
                 patch('ros.run_nav_calibration.os.killpg') as close:
                with self.assertRaises(SystemExit) as stopped:
                    run(out)
            self.assertEqual(stopped.exception.code,124)
            result=json.loads((Path(temp)/'episode_infra/shutdown.json').read_text())
            self.assertEqual(result['client_returncode'],124)
            close.assert_called()
