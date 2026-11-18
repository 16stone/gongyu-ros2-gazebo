"""Freeze geometric descendants separately; never rewrite C0 or earlier M1 evidence."""
import copy
import hashlib
import json
from pathlib import Path
from gongyu.geometry import default_geometry


def geometry_card(base,visible_loading=False):
    card=copy.deepcopy(base)
    card['id']='G_'+base['id']+('_visibleL' if visible_loading else '')
    card['version']='2.0-geometric-stationary-contacts'
    card['geometry']=default_geometry()
    if visible_loading:
        card['geometry']['device']=[6.2,0,.8]
    card['note']='Geometric camera/radio regions at stationary waypoints; uniform capability model. Bypass has a true 12m polyline. No collision/dynamic-flight validation. Visible-L control only moves device marker; sensors remain enabled.'
    return card


def main():
    root=Path(__file__).resolve().parent
    cards=[root/'scenarios/M1.json']+sorted((root/'scenarios').glob('M1_t*.json'))
    hashes={}
    for p in cards:
        base=json.loads(p.read_text())
        for visible in ((False,True) if p.stem=='M1' else (False,)):
            card=geometry_card(base,visible)
            dest=root/'scenarios'/f'{card["id"]}.json'
            if dest.exists():
                raise FileExistsError(dest)
            dest.write_text(json.dumps(card,indent=2)+'\n')
            hashes[dest.name]=hashlib.sha256(dest.read_bytes()).hexdigest()
    receipt=root/'evidence/phase03_setup/geometric_cards.json'
    receipt.write_text(json.dumps(hashes,indent=2)+'\n')
    print(json.dumps(hashes,indent=2))

if __name__=='__main__':
    main()
