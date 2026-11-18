"""Second physical development layout after the preserved west-exit blockage."""
import json,math
from pathlib import Path
from freeze_delivery_approach import delivery_card


def clearance_card():
    card=delivery_card();card.update(id='G2_D_clearance_development_v2_1',version='G2-D-clearance-development-v2.1')
    card['physical_berths']['D']=[[.5,0.],[-.8,-1.3],[.9,-2.],[-.7,1.5],[-2.6,-1.3],[-2.5,1.5]]
    card['physical_delivery_waypoint']=[1.8,1.5,.3]
    card['physical_timing_basis']['D_clearance_revision']='After preserved phase44 west-exit blockage: keep parked D peers away from exit(2,0); first four slots at(.5,0),(-.8,-1.3),(.9,-2),(-.7,1.5), with two spare slots farther west. Physical W>D only uses waypoint(1.8,1.5); abstract geometry/edge lengths and D>W remain unchanged. Actual parking is included in generated bounds. Task deadlines, speed, safety, report rules and nominal time estimates retained, new physical travel/queue time uncalibrated. Development trial, not holdout or GPU-only comparison. Phase45 invalid abstract-route card was rejected before mission; v2.1 separates physical staging.'
    card['physical_note']='D slots have minimum1.8m spacing, minimum1.5m west-exit clearance and FIFO final approach. New scene bounds include all physical slots; other parking unchanged. Acceptance remains.1m.'
    points=card['physical_berths']['D']
    assert min(math.dist(a,b) for i,a in enumerate(points) for b in points[i+1:])>=1.8-1e-12
    assert min(math.dist(p,[2.,0.]) for p in points)>=1.5-1e-12
    return card


if __name__=='__main__':
    import sys
    with Path(sys.argv[1]).open('x') as f:json.dump(clearance_card(),f,indent=2)
