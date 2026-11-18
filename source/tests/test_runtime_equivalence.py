# -*- coding: utf-8 -*-
"""phase107 运行时等价性的自动回归保护。

freeze_graph_baseline_phase107.py 声称「重构后重算同一摘要，行为漂移即失败」；
本测试把十组事件流的完整 SHA256 摘要固化在源码里，使 unittest discover 能直接检测漂移，
不依赖交付包外的路径。摘要算法与冻结脚本逐字一致：逐事件取 t_ms|actor|kind|task_id，
行间以换行连接后取 SHA256。
"""
import hashlib
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from freeze_m2 import m2_card                      # noqa: E402
from gongyu.run import simulate                    # noqa: E402
from gongyu.world import load_card                 # noqa: E402

# case -> (完整 digest, 事件数)；来源：验证/graph_baseline_phase107_post3.json
FROZEN = {
    'C0.json': ('f29305b8996ed896b242792a078850bb190792eced7018195efd06f7ec460cb1', 156),
    'G_M1.json': ('6243f651ccb0dfa50a696f31ceb5825d64824c5d1597a6be362bca650cd72215', 218),
    'M1.json': ('2302b4827443d3b641e4b8b8e49f0b17b8b4ac4a6f6cc950e1b95653a2efdf7a', 214),
    'M1_t6000_r0_p12000.json': ('2302b4827443d3b641e4b8b8e49f0b17b8b4ac4a6f6cc950e1b95653a2efdf7a', 214),
    'M2_autonomous_P0': ('2b8e3aa8568fc987cf98fb62d9900f414b172cb52b5763117f24bb57d5893e21', 346),
    'M2_autonomous_P3': ('8de22846c217218b5142bfa0b3a4025b4031fad007d855f57b731c1ae784161a', 474),
    'M2_fixed_P0': ('46c2763465130426c933ac9dd4e53c99edb4e976a5e89ecfeca5a0c15d6258fb', 330),
    'M2_fixed_P3': ('fbe50231bbd45b7fea98173de259b49b6a1cf311e2abb6f9faa96b13c0c3abc7', 494),
    'M2_route_only_P0': ('ef7507db0970d4defc746193797d24e206b07c255dc2109217287c63959e9923', 385),
    'M2_route_only_P3': ('96a37d289460276a25dc47a9ef1065ecfecd21efc1c03e966cfe01f17645651b', 484),
}


def digest(result):
    rows = []
    for e in result.events:
        d = e if isinstance(e, dict) else e.__dict__
        rows.append('|'.join(str(d.get(k, '')) for k in ('t_ms', 'actor', 'kind', 'task_id')))
    return hashlib.sha256('\n'.join(rows).encode()).hexdigest()


def cases():
    out = []
    for name in ('M1.json', 'C0.json', 'G_M1.json', 'M1_t6000_r0_p12000.json'):
        p = HERE / 'scenarios' / name
        if p.exists():
            out.append((name, load_card(p), 'P3'))
    for mode in ('fixed', 'route_only', 'autonomous'):
        for policy in ('P0', 'P3'):
            card = m2_card(service=True)
            card['m2']['red_route_policy'] = mode
            card['id'] = 'M2_' + mode + '_service1_' + policy
            out.append(('M2_' + mode + '_' + policy, card, policy))
    return out


class RuntimeEquivalenceFrozenDigest(unittest.TestCase):
    def test_ten_case_digests_are_immutable(self):
        """十组摘要逐条与冻结常量一致；改动运行时行为会导致本用例失败。"""
        self.assertEqual(len(FROZEN), 10)
        self.assertEqual(FROZEN['M1.json'][0], FROZEN['M1_t6000_r0_p12000.json'][0],
                         'M1 与其时间参数变体本应给出同一事件流')
        built = cases()
        self.assertEqual(len(built), 10, 'scenario cards must all be present')
        for name, card, policy in built:
            self.assertIn(name, FROZEN, name)
            r = simulate(card, policy, name)
            self.assertEqual(digest(r), FROZEN[name][0], name)
            self.assertEqual(len(r.events), FROZEN[name][1], name)


if __name__ == '__main__':
    unittest.main()
