"""Bounded native screenshot capture; observation failure is not mission failure."""
import hashlib,json,os,subprocess,time
from pathlib import Path


def capture_native(directory,label,emit,run=None):
    if os.environ.get('GONGYU_HEADLESS') == '1':
        emit('referee','screenshot_unavailable',dict(label=label, reason='headless server'))
        return False
    run=run or subprocess.run
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    before=set(directory.glob('*.png'))
    for attempt in (1,2):
        receipt=dict(label=label,attempt=attempt)
        try:
            result=run(['gz','service','-s','/gui/screenshot','--reqtype','gz.msgs.StringMsg',
                '--reptype','gz.msgs.Boolean','--timeout','5000','--req',
                'data: '+json.dumps(str(directory.resolve()))],capture_output=True,text=True,timeout=8)
            receipt.update(returncode=result.returncode,stdout=result.stdout,stderr=result.stderr)
        except (subprocess.TimeoutExpired,OSError) as exc:
            receipt['error']=repr(exc)
        files=[];deadline=time.monotonic()+2
        while True:
            for path in sorted(set(directory.glob('*.png'))-before):
                try:content=path.read_bytes()
                except OSError:continue
                # The GUI reply can arrive before its asynchronous PNG write has finished.
                if content[:8]==b'\x89PNG\r\n\x1a\n' and content.endswith(b'\x00\x00\x00\x00IEND\xaeB\x60\x82'):
                    files.append(dict(file=path.name,bytes=len(content),sha256=hashlib.sha256(content).hexdigest()))
            if files or time.monotonic()>=deadline:break
            time.sleep(.05)
        receipt.update(files=files,saved=bool(files))
        emit('referee','native_screenshot',receipt)
        if files:return True
    emit('referee','screenshot_unavailable',dict(label=label,attempts=2))
    return False
