"""Explicit physical parking positions; claims survive dispatch until real departure."""
import copy
import math


def physical_card(card):
    card=copy.deepcopy(card);layout={}
    for node,capacity in card['berth_capacity'].items():
        if not 1<=capacity<=7:raise ValueError('physical parking layout supports capacity one through seven')
        x,y=card['nodes'][node];offsets=[(0.,0.)]
        if node=='W':x-=.2
        if node=='E':x+=.25
        if capacity==2:
            side=.95 if node in ('E','W') else .4
            offsets=[(0.,-side),(0.,side)]
            if node=='L':offsets=[(.05,0.),(.05,.8)]
        elif capacity>2:
            offsets=[(-.8*(i%2),.8*((i//2+1)//2)*(1 if (i//2)%2 else -1)) for i in range(capacity)]
        layout[node]=[[x+dx,y+dy] for dx,dy in offsets]
    card['physical_berths']=layout;card['physical_berth_tolerance_m']=.1
    card['physical_channel_clear_width_m']=1.0
    card['physical_contact_hold_ms']=6000
    card['physical_departure_clearance_m']=3.0
    card['physical_note']='Explicit .8m parking spacing and .1m parking acceptance; nominal graph distances require physical timing calibration.'
    return card


class Berths:
    def __init__(self,card):
        self.card=card;self.claims={}
        for actor,spec in card['fleet'].items():
            if self.reserve(actor,spec['node']) is None:raise ValueError('initial physical berths exhausted')

    def reserve(self,actor,node):
        if (actor,node) in self.claims:return self.position(actor,node)
        used={i for (a,n),i in self.claims.items() if n==node}
        free=next((i for i in range(len(self.card['physical_berths'][node])) if i not in used),None)
        if free is None:return None
        self.claims[actor,node]=free
        return self.position(actor,node)

    def position(self,actor,node):
        if (actor,node) not in self.claims:return None
        x,y=self.card['physical_berths'][node][self.claims[actor,node]]
        mode=self.card['fleet'][actor]['mode'];heights=self.card['geometry']['heights']
        z=heights['ground' if mode=='ground' else 'blue_air' if actor.startswith('B') else 'red_air']
        return (x,y,z)

    def release(self,actor,node):
        self.claims.pop((actor,node),None)
