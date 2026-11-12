"""Bounded local observation; never changes configuration or submits game actions."""
import argparse
import json
from pathlib import Path
import time
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dps_assistant.loopback import loopback_opener
urlopen=loopback_opener().open

parser=argparse.ArgumentParser()
parser.add_argument('--seconds',type=int,default=300)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
args.output.mkdir(parents=True,exist_ok=True)
started=time.time();deadline=started+args.seconds;first={};latest={};events={};errors=[];samples=0
while True:
    try:
        with urlopen('http://127.0.0.1:17860/api/state',timeout=10) as response:data=json.load(response)
        sample={'at':time.time(),'instances':data['instances'],'validation':data['validation']}
        with (args.output/'samples.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(sample,ensure_ascii=False)+'\n')
        samples+=1
        for row in data['instances']:
            if row.get('identity') and row.get('snapshot'):
                first.setdefault(row['identity'],row);latest[row['identity']]=row
        for event in data['events']:
            if event['at']>=started:events[json.dumps(event,sort_keys=True)]=event
    except Exception as exc:errors.append({'at':time.time(),'error':str(exc)})
    report={'started':started,'observed_until':time.time(),'required_seconds':args.seconds,'complete':time.time()>=deadline,
            'samples':samples,'first':first,'latest':latest,'events':sorted(events.values(),key=lambda e:e['at']),'errors':errors}
    target=args.output/'report.json';temporary=target.with_suffix('.tmp')
    temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(target)
    if report['complete']:break
    time.sleep(min(15,max(0,deadline-time.time())))
print(json.dumps({'seconds':round(time.time()-started),'samples':samples,'errors':len(errors),'report':str(target)},ensure_ascii=False))
