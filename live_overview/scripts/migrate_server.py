#!/usr/bin/env python3
"""Export schedule, mappings and peaks; excludes tokens, old telemetry and personal roster."""
import argparse,json,os
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--source',default='/opt/ismir-live')
p.add_argument('--clock',help='Explicit conference-clock.json path; omitting starts with real time')
p.add_argument('--output',required=True)
a=p.parse_args();root=Path(a.source)
schedule=json.loads((root/'data/schedule.json').read_text())
runtime=json.loads((root/'data/runtime.json').read_text()) if (root/'data/runtime.json').exists() else {}
result={'schedule':schedule,'runtime':{'observerRoomMappings':runtime.get('observerRoomMappings',{}),'events':{k:{'peakZoom':v.get('peakZoom',0)} for k,v in runtime.get('events',{}).items()},'posters':{k:{'peakZoom':v.get('peakZoom',0)} for k,v in runtime.get('posters',{}).items()}},'clock':json.loads(Path(a.clock).read_text()) if a.clock else {'enabled':False}}
fd=os.open(a.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f:json.dump(result,f,ensure_ascii=False,indent=2)
print('Exported schedule/mappings/peaks. No OAuth tokens or live telemetry included.')
