"""Physical development profile after the preserved phase38 D approach failure."""
import json, math
from pathlib import Path
from freeze_g2 import g2_card


def delivery_card():
    card=g2_card()
    card.update(id='G2_D_approach_development_v1',version='G2-D-approach-development-v1')
    card['physical_arrival_mutex_nodes']=['D']
    card['physical_berths']['D']=[[x,y] for y in (0.,1.35,-1.35) for x in (1.2,-.15)]
    card['physical_timing_basis']['D_approach_revision']='After phase38 failure: FIFO final D approach, retained across E>W>D until actual arrival dwell; D parking spacing1.35m. Old tasks, deadlines, speeds and nominal edge estimates unchanged. Additional movement/queue time is uncalibrated; this is development, not an untuned holdout or a GPU-only comparison.'
    card['physical_note']='D uses1.35m spacing and final approach FIFO; other parking layouts unchanged. Physical arrival acceptance remains.1m.'
    points=card['physical_berths']['D']
    assert min(math.dist(a,b) for i,a in enumerate(points) for b in points[i+1:])>=1.35-1e-12
    return card


if __name__=='__main__':
    import sys
    with Path(sys.argv[1]).open('x') as f:json.dump(delivery_card(),f,indent=2)
