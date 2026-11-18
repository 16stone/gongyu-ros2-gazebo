"""Start and cleanly stop only the navigation stack owned by this run."""
import argparse
import json
import os
import signal
import subprocess
from pathlib import Path


def run(out):
    out=Path(out).resolve();infra=out.with_name(out.name+'_infra')
    if out.exists() or infra.exists():
        raise FileExistsError('each navigation run requires new evidence and infrastructure directories')
    infra.mkdir(parents=True)
    env=dict(os.environ,ROS_DOMAIN_ID='82',GZ_IP='127.0.0.1',GZ_PARTITION='gongyu_nav_20261029')
    with (infra/'stack.log').open('w') as stack_log,(infra/'client.log').open('w') as client_log:
        process=subprocess.Popen(['ros2','launch','ros/nav_calibration.launch.py'],env=env,
            stdout=stack_log,stderr=subprocess.STDOUT,start_new_session=True)
        code=124
        try:
            client=subprocess.run(['python3','-m','ros.nav_acceptance',str(out)],env=env,
                stdout=client_log,stderr=subprocess.STDOUT,timeout=300)
            code=client.returncode
        except subprocess.TimeoutExpired:
            client_log.write('\nAcceptance client exceeded the 300-second wall-clock limit.\n')
        finally:
            for sig,seconds in ((signal.SIGINT,15),(signal.SIGTERM,5),(signal.SIGKILL,3)):
                try:
                    os.killpg(process.pid,sig)
                except ProcessLookupError:
                    break
                try:
                    process.wait(timeout=seconds)
                except subprocess.TimeoutExpired:
                    continue
            process.wait()
    (infra/'shutdown.json').write_text(json.dumps({'owned_process_group':process.pid,
        'launch_returncode':process.returncode,'client_returncode':code},indent=2)+'\n')
    print(json.dumps({'output':str(out),'client_returncode':code}),flush=True)
    if code:
        raise SystemExit(code)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
