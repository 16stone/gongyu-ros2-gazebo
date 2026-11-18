"""Save all four Appendix-B checkpoint outcomes with raw events and timing plots."""
import argparse
import csv
import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path

from gongyu.c1 import simulate


def run(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    dirty=bool(subprocess.check_output(['git','diff','HEAD','--name-only'],text=True).strip())
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('gongyu').glob('*.py'))}
    hashes['run_c1.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    cases=[('baseline',{'service':False}),('mutual',{}),
           ('refusal',{'air_deadline_ms':14000}),('late',{'delay_ms':3000})]
    results=[]
    for label,kwargs in cases:
        started=datetime.now(timezone.utc).isoformat()
        r=simulate(**kwargs);dest=out/r['run_id'];dest.mkdir()
        events=r.pop('events');trajectory=r.pop('trajectories')
        for filename,rows in [('events',[asdict(e) for e in events]),
                ('decisions',[asdict(e) for e in events if e.kind=='contract_state' and e.payload.get('candidates')])]:
            (dest/(filename+'.jsonl')).write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows))
        with (dest/'trajectory.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,list(trajectory[0]));writer.writeheader();writer.writerows(trajectory)
        card={'id':r['run_id'],'type':'Appendix_B_checkpoint','parameters':{
            'air_deadline_ms':kwargs.get('air_deadline_ms',18000),'delay_ms':kwargs.get('delay_ms',1000),
            'service':kwargs.get('service',True)},'label':label,
            'fleet':['B1','R1','R5'],'given_reservations':{'early':[20000,26000],'late':[28000,34000]},
            'scope':'C1 three-robot graph checkpoint; not M2 or physical simulation'}
        card_text=json.dumps(card,indent=2,ensure_ascii=False)+'\n'
        (dest/'scenario.json').write_text(card_text)
        manifest={'run_id':r['run_id'],'backend':'graph_checkpoint_C1','code_revision':revision,
            'code_dirty':dirty,'code_sha256':hashes,'started_at':started,
            'finished_at':datetime.now(timezone.utc).isoformat(),
            'card_file_sha256':hashlib.sha256(card_text.encode()).hexdigest(),
            'boundary_injection':kwargs.get('delay_ms',1000)!=1000,'limitations':r['limitations']}
        (dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        (dest/'metrics.json').write_text(json.dumps(r,indent=2)+'\n')
        assert not r['violations']
        results.append((label,r,events))
    plot(out,results)
    comparison=[{'label':label,**r} for label,r,_ in results]
    (out/'comparison.json').write_text(json.dumps(comparison,indent=2)+'\n')
    artifact_hashes={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(out.rglob('*')) if p.is_file()}
    (out/'artifact_sha256.json').write_text(json.dumps(artifact_hashes,indent=2)+'\n')
    print(json.dumps(comparison,indent=2))


def plot(out,results):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(4,1,figsize=(11,10),constrained_layout=True)
    actors=['B1','R1','R5']
    colors={'move':'#4f85a0','cross':'#df9c5d','observe':'#8bb190',
        'load_service':'#8bb190','unload':'#a9c4b2','inspect':'#ae97be','committed_observation':'#c7c5be'}
    for ax,(label,r,events) in zip(axes,results):
        for e in events:
            if e.kind=='slot_exchange_committed':
                ax.axvline(e.t_ms/1000,color='#4a6d55',ls=':',lw=1)
            if e.actor not in actors:
                continue
            y=actors.index(e.actor)
            kind=e.kind.removesuffix('_started')
            if e.kind.endswith('_started') and kind in colors:
                ax.broken_barh([(e.t_ms/1000,e.payload['duration_ms']/1000)],(y-.23,.46),facecolors=colors[kind])
            elif e.kind in ('delivery','inspection'):
                ax.scatter(e.t_ms/1000,y,marker='*',s=100,color='black',zorder=3)
                ax.annotate(f'{e.t_ms/1000:g}s',(e.t_ms/1000,y),xytext=(4,8),textcoords='offset points',fontsize=8)
        report=next((e for e in events if e.actor=='B1' and e.kind=='contract_state' and e.payload['state']=='FULFILLED'),None)
        if report:
            ax.annotate('sample 8s / receive & accept 9s',(9,0),xytext=(12,-.5),arrowprops={'arrowstyle':'->'},fontsize=8)
        ax.set(yticks=range(3),yticklabels=actors,xlim=(0,60),ylim=(2.6,-.8),
            title=f"{label}: local contract {r['contracts']} | B1 active {r['active_ms']['B1']/1000:g}s, wait {r['waiting_ms']['B1']/1000:g}s")
        ax.grid(axis='x',alpha=.2)
    axes[-1].set_xlabel('Actual checkpoint simulation time (s); stars = accepted task completion')
    fig.suptitle('C1 bilateral exchange: actual event traces\nThree robots; fixed checkpoint forecasts. Late case injects 3s delay into a fixed 8s quote.',fontsize=12)
    fig.savefig(out/'contract_timeline.png',dpi=180)
    fig.savefig(out/'contract_timeline.svg')
    plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');run(p.parse_args().out)
