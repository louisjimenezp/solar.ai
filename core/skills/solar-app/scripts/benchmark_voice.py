#!/usr/bin/env python3
"""Measure real conductor calls; does not dispatch tasks or mutate model setup."""
import argparse
import json
from pathlib import Path
import statistics
import time
from voice_conductor import decide

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--samples',type=int,default=30)
    args=parser.parse_args()
    if not 1 <= args.samples <= 100: parser.error('samples must be 1..100')
    results=[]
    cases=['Prepara un resumen sobre asistentes virtuales', '¿Qué encargos están activos?', 'Prepara una propuesta para el banco']
    for i in range(args.samples):
        start=time.monotonic()
        try:
            decision=decide(cases[i%len(cases)],[],Path(__file__).resolve().parents[4])
            result={'valid':True,'action':decision['action']}
        except Exception as exc: result={'valid':False,'error':str(exc)}
        result['seconds']=round(time.monotonic()-start,3)
        results.append(result)
        print(json.dumps({'sample':i+1,**result}),flush=True)
    values=sorted(r['seconds'] for r in results)
    print(json.dumps({'samples':len(results),'valid':sum(r['valid'] for r in results),
                     'p95_seconds':values[min(len(values)-1, int(len(values)*.95))]}))
