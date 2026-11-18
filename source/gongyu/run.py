import argparse
import csv
import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from .policies import controllers
from .runtime import Link, run_episode
from .world import World, load_card


def simulate(card,policy='P0',run_id=None,link=None):
    """Run one card through one runtime per entity and one referee.

    The historical single loop is kept as the zero-delay special case: with no
    link the runtimes hold live views, so the event stream is identical to the
    shared-object implementation. Passing `link=Link(...)` makes the knowledge
    channel explicit and lets it age or drop.
    """
    return run_episode(card,policy,run_id,link=link)


def write_result(result,card,policy,out,started,case_path=None):
    out = Path(out)
    out.mkdir(parents=True,exist_ok=False)
    for name,rows in (('events',result.events),('decisions',result.decisions),('diagnostics',getattr(result,'diagnostics',[]))):
        with (out/(name+'.jsonl')).open('w',encoding='utf-8') as f:
            for row in rows:
                f.write(json.dumps(row if isinstance(row,dict) else asdict(row),ensure_ascii=False)+'\n')
    (out/'metrics.json').write_text(json.dumps(result.metrics,indent=2,ensure_ascii=False),encoding='utf-8')
    for name,rows,fields in (
        ('trajectory',result.trajectories,['t_ms','actor','x','y','z','node']),
        ('task_timeline',[{'task_id':k,**v} for k,v in result.metrics['tasks'].items()],
         ['task_id','completed_ms','on_time','deadline_ms','team'])):
        with (out/(name+'.csv')).open('w',newline='',encoding='utf-8') as f:
            writer = csv.DictWriter(f,fields)
            writer.writeheader()
            writer.writerows(rows)
    try:
        source_root=Path(__file__).resolve().parents[1]
        revision = subprocess.check_output(['git','rev-parse','HEAD'],cwd=source_root,stderr=subprocess.DEVNULL,text=True).strip()
        dirty = bool(subprocess.check_output(['git','status','--porcelain'],cwd=source_root,text=True).strip())
    except (subprocess.CalledProcessError,FileNotFoundError):
        revision,dirty = 'uncommitted',True
    code_hashes = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}
    manifest = {'run_id':result.events[0].run_id,'backend':'graph','policy':policy,'seed':card['seed'],
                'card_sha256':hashlib.sha256(json.dumps(card,sort_keys=True).encode()).hexdigest(),
                'card_file_sha256':hashlib.sha256(Path(case_path).read_bytes()).hexdigest() if case_path else None,
                'code_revision':revision,'code_dirty':dirty,'code_sha256':code_hashes,
                'started_at':started,'finished_at':datetime.now(timezone.utc).isoformat(),
                'infrastructure_valid':True,'external_witness':policy=='witness',
                'limitations':['graph kinematics; no collision or Gazebo validation',
                    ('3D occlusion/range checks with stationary waypoint radio contacts; no physical camera/RF calibration'
                     if 'geometry' in card else 'explicit graph visibility and radio regions; geometric sensing pending'),
                    ('action-boundary repair of the current deliveries with acknowledged release; no moving-actuator preemption or arbitrary fleet task allocation'
                     if card.get('online_replanning') else 'finite initial search and boundary report recovery; repeated online plan repair pending'),
                    'shared patrol forecast is conditional; real prepare/commit and arrival still required']}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (out/'scenario.json').write_text(json.dumps(card,indent=2,ensure_ascii=False),encoding='utf-8')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--case',required=True)
    p.add_argument('--blue',choices=['P0','P1','P2','P3','P2_equal','witness'],default='P0')
    p.add_argument('--red',choices=['task'],default='task')
    p.add_argument('--seed',type=int,default=0)
    p.add_argument('--out',required=True)
    args = p.parse_args()
    card = load_card(args.case)
    if args.seed != card['seed']:
        raise ValueError('seed must match frozen card')
    start = datetime.now(timezone.utc).isoformat()
    result = simulate(card,args.blue,Path(args.out).name)
    write_result(result,card,args.blue,args.out,start,args.case)
    print(json.dumps(result.metrics,indent=2))

if __name__ == '__main__':
    main()
