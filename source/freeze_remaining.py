"""Residual checkpoint calibration, explicitly separate from the full M1 prefix."""
import copy
import json
from pathlib import Path

from gongyu.world import load_card


def residual_card():
    root=Path(__file__).resolve().parent
    card=copy.deepcopy(load_card(root/'scenarios/G_M1_t20000_r0_p12000.json'))
    card.update(id='R_remaining_cached',version='1.0',end_ms=60000,online_replanning=True,
        residual_checkpoint=True,red_channel_enabled=False,
        initial_reports={'B1':-30000,'B2':-8000},initial_completed={
            'blue1':{'actor':'B1','completed_ms':-1000},
            'blue_inspect':{'actor':'B3','completed_ms':-10000},
            'red1':{'actor':'R1','completed_ms':-1000},
            'red2':{'actor':'R2','completed_ms':-1000}})
    for actor,node in {'B1':'D','B2':'L','B3':'K','R1':'D','R2':'D'}.items():
        card['fleet'][actor]['node']=node
    for task in card['tasks']:
        task['release_ms']=-30000 if task['id'] in card['initial_completed'] else 0
        if task['id']=='blue2':
            task['deadline_ms']=18000
    card['note']='Residual checkpoint: blue1 and earlier private tasks already completed; B2 carried an O report for 8s to L. Only blue2 remains. No claim of a full causal M1 prefix.'
    return card


def residual_air_card():
    card=residual_card()
    card.update(id='R_remaining_air',tau_ms=6000,initial_reports={'B1':-30000,'B2':-30000})
    card['fleet']['B1']['node']='L';card['fleet']['B2']['node']='J'
    next(t for t in card['tasks'] if t['id']=='blue2')['deadline_ms']=25000
    card['note']='Residual checkpoint with stale ground reports and completed prior air inspection. Fresh air observation may be requested through real prepare/commit. Not a full M1 prefix.'
    return card


if __name__=='__main__':
    for card in (residual_card(),residual_air_card()):
        path=Path(__file__).resolve().parent/'scenarios'/f'{card["id"]}.json'
        if path.exists():
            raise FileExistsError(path)
        path.write_text(json.dumps(card,indent=2)+'\n')
