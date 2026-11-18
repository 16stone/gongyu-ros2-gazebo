import base64,hashlib,subprocess,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from ros.capture import capture_native

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aGNsAAAAASUVORK5CYII=')

class Capture(unittest.TestCase):
    def test_async_png_write_finishes_before_receipt_is_hashed(self):
        events=[];writers=[]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'frame.png'
            def run(*args,**kwargs):
                path.write_bytes(PNG[:32])
                def finish():
                    time.sleep(.05)
                    with path.open('ab') as stream:stream.write(PNG[32:])
                worker=threading.Thread(target=finish);worker.start();writers.append(worker)
                return SimpleNamespace(returncode=0,stdout='data: true',stderr='')
            try:
                self.assertTrue(capture_native(tmp,'ready',lambda *a:events.append(a),run))
                self.assertEqual(events[-1][2]['files'][0]['bytes'],len(PNG))
                self.assertEqual(events[-1][2]['files'][0]['sha256'],hashlib.sha256(PNG).hexdigest())
            finally:
                for worker in writers:worker.join()

    def test_incomplete_png_is_not_successful_evidence(self):
        events=[]
        with tempfile.TemporaryDirectory() as tmp:
            def run(*args,**kwargs):
                (Path(tmp)/'frame.png').write_bytes(PNG[:32])
                return SimpleNamespace(returncode=0,stdout='data: true',stderr='')
            self.assertFalse(capture_native(tmp,'ready',lambda *a:events.append(a),run))
        self.assertEqual(events[-1][1],'screenshot_unavailable')

    def test_transient_service_failure_retries_and_records_actual_file(self):
        events=[];calls=[]
        with tempfile.TemporaryDirectory() as tmp:
            def run(*args,**kwargs):
                calls.append(args)
                if len(calls)==1:raise subprocess.TimeoutExpired('gz',8)
                (Path(tmp)/'frame.png').write_bytes(PNG)
                return SimpleNamespace(returncode=0,stdout='data: true',stderr='')
            self.assertTrue(capture_native(tmp,'ready',lambda *a:events.append(a),run))
        self.assertEqual(len(calls),2)
        self.assertEqual(events[-1][2]['files'][0]['bytes'],len(PNG))
        self.assertTrue(events[-1][2]['saved'])

    def test_boolean_success_or_old_file_cannot_fake_saved_evidence(self):
        events=[];calls=[]
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'old.png').write_bytes(PNG)
            def run(*args,**kwargs):
                calls.append(args);return SimpleNamespace(returncode=0,stdout='data: true',stderr='')
            self.assertFalse(capture_native(tmp,'ready',lambda *a:events.append(a),run))
        self.assertEqual(len(calls),2)
        self.assertEqual(events[-1][1],'screenshot_unavailable')
