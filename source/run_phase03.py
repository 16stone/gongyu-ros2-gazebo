"""Geometric conditions reuse the same execution and comparison runner."""
import argparse
from pathlib import Path
from run_phase02 import run_cases

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');args=p.parse_args()
    root=Path(__file__).resolve().parent
    cases=sorted((root/'scenarios').glob('G_M1_t*.json'))+[root/'scenarios/G_M1_visibleL.json']
    run_cases(cases,args.out)