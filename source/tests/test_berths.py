import copy,math,unittest
from freeze_m2 import m2_card
from gongyu.berths import Berths,physical_card
from gongyu.physical_world import PhysicalWorld
from gongyu.geometry import Geometry


class BerthTests(unittest.TestCase):
    def test_initial_and_destination_claims_have_separate_physical_positions(self):
        card=physical_card(m2_card());pool=Berths(card)
        self.assertGreaterEqual(math.dist(pool.position('R1','E'),pool.position('R2','E')),.79)
        self.assertIsNone(pool.reserve('B1','E'))
        self.assertIsNotNone(pool.reserve('R1','D'))
        self.assertNotEqual(pool.position('R1','D'),pool.position('B1','D'))
        self.assertIsNotNone(pool.position('R1','E'))

    def test_motion_request_does_not_release_source_until_matching_actual_departure(self):
        sent=[];w=PhysicalWorld(physical_card(m2_card()),'berths',lambda *a:sent.append(a))
        p=w.berths.position('B1','D');w.receive_pose('B1',p,0.,0.,0)
        self.assertTrue(w.start_move('B1','W'))
        self.assertIsNotNone(w.berths.position('B1','D'))
        token=sent[-1][1];w.advance(100)
        w.receive_pose('B1',(p[0]+.6,p[1],p[2]),.2,0.,100,token)
        self.assertIsNone(w.berths.position('B1','D'))
        self.assertIsNotNone(w.berths.position('B1','W'))

    def test_nominal_center_cannot_satisfy_an_offset_berth_arrival(self):
        sent=[];w=PhysicalWorld(physical_card(m2_card()),'berths',lambda *a:sent.append(a))
        p=w.berths.position('B1','D');w.receive_pose('B1',p,0.,0.,0);w.start_move('B1','W')
        token=sent[-1][1]
        for t in range(100,1500,100):
            w.advance(t);w.receive_pose('B1',(2.,0.,.3),0.,0.,t,token,True)
        w.advance(1500);self.assertIsNone(w.poses['B1'])

    def test_other_occupied_berth_is_not_a_mandatory_entry_waypoint(self):
        card=m2_card();card['fleet']['R1']['node']='W';sent=[]
        w=PhysicalWorld(physical_card(card),'entry',lambda *a:sent.append(a))
        occupied=w.berths.position('B1','D');p=w.berths.position('R1','W')
        w.receive_pose('R1',p,0.,0.,0);self.assertTrue(w.start_move('R1','D'))
        self.assertNotIn(occupied,sent[-1][2])

    def test_parking_positions_are_separated_across_adjacent_regions(self):
        card=physical_card(m2_card())
        positions=[(n,p) for n,ps in card['physical_berths'].items() for p in ps]
        for i,(n,p) in enumerate(positions):
            for other,q in positions[i+1:]:self.assertGreaterEqual(math.dist(p,q),.79,(n,other,p,q))

    def test_channel_goals_force_interior_transit_without_an_interior_turn(self):
        for source,target in [('E','W'),('W','E')]:
            with self.subTest(direction=(source,target)):
                card=m2_card();card['fleet']['R1']['node']=source;sent=[]
                w=PhysicalWorld(physical_card(card),'channel',lambda *a:sent.append(a))
                p=w.berths.position('R1',source);w.receive_pose('R1',p,0.,0.,0)
                self.assertTrue(w.start_move('R1',target));route=sent[-1][2]
                interior=[i for i,p in enumerate(route) if 2.35<p[0]<4.65]
                self.assertGreaterEqual(len(interior),2,'endpoints alone allow Nav2 to bypass the physical tunnel')
                for i in interior:
                    self.assertEqual(route[i][1],0.)
                    self.assertEqual(route[i+1][1],route[i][1], 'interior goal yaw must stay along the tunnel axis')
                for node in (source,target):self.assertIn(tuple(w.card['nodes'][node])+(.3,),route)
                self.assertEqual(route[-1],w.berths.position('R1',target))

    def test_east_departure_aligns_before_the_occupied_information_region(self):
        sent=[];w=PhysicalWorld(physical_card(m2_card()),'entry',lambda *a:sent.append(a))
        p=w.berths.position('R1','E');w.receive_pose('R1',p,0.,0.,0)
        self.assertTrue(w.start_move('R1','W'))
        alignment=sent[-1][2][1]
        self.assertEqual(alignment,(5.,0.,.3))
        # The full turning guard plus peer radius and both .1m pose errors must fit.
        peers=w.card['physical_berths']['L']+[list(w.reference_position('R2','E')[:2])]
        for peer in peers:self.assertGreater(math.dist(alignment[:2],peer),.5+.22+.2)

    def test_both_information_berths_keep_radio_contact_with_bounded_position_errors(self):
        card=physical_card(m2_card());geometry=Geometry(card['geometry'])
        k=(*card['nodes']['K'],card['geometry']['heights']['blue_air'])
        for x,y in card['physical_berths']['L']:
            # Both endpoints can be .1m off horizontally; aircraft height can be .2m off.
            for i in range(72):
                dx=.2*math.cos(i*math.pi/36);dy=.2*math.sin(i*math.pi/36)
                for dz in (-.2,.2):
                    self.assertTrue(geometry.radio((x+dx,y+dy,.3),(k[0],k[1],k[2]+dz)),(x,y,i,dz))

    def test_same_exit_follower_waits_only_until_predecessor_clears_local_exit(self):
        card=m2_card();card['fleet']['B1']['node']='L';card['fleet']['B2']['node']='L';sent=[]
        w=PhysicalWorld(physical_card(card),'egress',lambda *a:sent.append(a))
        initial={a:w.reference_position(a,'L') for a in ('B1','B2')}
        for a,p in initial.items():w.receive_pose(a,p,0.,0.,0)
        self.assertTrue(w.start_move('B1','D'))
        self.assertFalse(w.start_move('B2','D'))
        self.assertIsNone(w.berths.position('B2','D'))
        token=sent[-1][1];w.advance(100);p=initial['B1']
        w.receive_pose('B1',(p[0],p[1]-.6,p[2]),.2,0.,100,token)
        w.receive_pose('B2',initial['B2'],0.,0.,100)
        self.assertIsNone(w.berths.position('B1','L'))
        self.assertFalse(w.start_move('B2','D'),'free parking claim does not mean the moving peer cleared the local costmap')
        w.advance(200);w.receive_pose('B1',(p[0],p[1]-2.4,p[2]),.2,0.,200,token)
        w.receive_pose('B2',initial['B2'],0.,0.,200)
        self.assertTrue(w.start_move('B2','D'))
        self.assertIn('B1',w.moves,'guard must not serialize the entire transport trip')
        self.assertEqual(len(sent),2)

    def test_a_different_exit_is_not_serialized_with_the_predecessor(self):
        card=m2_card();card['fleet']['B1']['node']='L';card['fleet']['B2']['node']='L'
        w=PhysicalWorld(physical_card(card),'different_exit',lambda *args:None)
        for a in ('B1','B2'):w.receive_pose(a,w.reference_position(a,'L'),0.,0.,0)
        self.assertTrue(w.start_move('B1','D'));self.assertTrue(w.start_move('B2','J'))

    def test_wrong_mode_is_rejected_before_destination_allocation(self):
        card=m2_card();card['fleet']['B3']['node']='L'
        w=PhysicalWorld(physical_card(card),'mode',lambda *args:None)
        w.receive_pose('B3',w.reference_position('B3','L'),0.,0.,0)
        with self.assertRaises(ValueError):w.start_move('B3','D')
        self.assertIsNone(w.berths.position('B3','D'))


if __name__=='__main__':unittest.main()
