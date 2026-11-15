"""Offline grain ablation: synthetic pressure/angle/width controls and optional private page crop.

Run after cargo build --release --manifest-path native/redraw/Cargo.toml --bin render-json.
Outputs stay under ignored artifacts; reference is the calibrated renderer, not an app export.
"""
import argparse
import copy
import json
import hashlib
import math
import os
import shutil
import subprocess
import time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--output',default='artifacts/high-res-grain')
parser.add_argument('--renderer')
args=parser.parse_args()
OUT = ROOT / args.output
OUT.mkdir(parents=True, exist_ok=True)
executable = 'render-json.exe' if os.name == 'nt' else 'render-json'
EXE = OUT / executable
shutil.copy2(Path(args.renderer) if args.renderer else ROOT / 'native/redraw/target/release' / executable, EXE)
(OUT/'provenance.json').write_text(json.dumps({'renderer_sha256': hashlib.sha256(EXE.read_bytes()).hexdigest(),
    'reference':'calibrated default renderer, not an app export',
    'grain_variant':'experimental output-pixel occupancy with area-preserving shears',
    'display':'nearest-neighbor magnification at equal source scale'},indent=2),encoding='utf8')
records = []

def render(request, scale, refined):
    request = copy.deepcopy(request)
    w, h = request['page']['paper_size']
    request['options'] = {'viewport': {'width': round(w*scale), 'height': round(h*scale)}, 'high_res_grain': refined}
    src, dst = OUT/'request.json', OUT/'frame.rgba'
    src.write_text(json.dumps(request), encoding='utf8')
    start=time.perf_counter()
    result=subprocess.run([str(EXE), str(src), str(dst)], capture_output=True, check=True, text=True)
    elapsed=time.perf_counter()-start
    size=json.loads(result.stdout)
    return Image.frombytes('RGBA',(size['width'],size['height']),dst.read_bytes()).convert('RGB'),elapsed

def mass(image):
    return float((255-np.asarray(image,dtype=float)[:,:,0]).sum())

def control(pressure,width,angle,overlap=False):
    dx,dy=50*math.cos(angle),50*math.sin(angle)
    stroke={'stroke_id':'s','group_id':'g','rgba':[0,0,0,255],'thickness_scale':1,'tool_code':14,'points':[
        {'x':64-dx,'y':64-dy,'width':width*4,'pressure':pressure},
        {'x':64+dx,'y':64+dy,'width':width*4,'pressure':pressure}]}
    strokes=[stroke]
    if overlap:
        extra=copy.deepcopy(stroke);extra['stroke_id']='s2'
        for p in extra['points']: p['y']+=3
        strokes.append(extra)
    return {'page':{'page_id':'control','paper_size':[128,128],'groups':[{'group_id':'g','visible':True}], 'compositing_order':['g'],'strokes':strokes}}

samples=[]
for scale in [1,1.5,2,4]:
    for pressure in [16,32,64,128,192,255]:
        for width,angle,overlap in [(8,0,False),(20,.6,False),(32,1.57,True)]:
            req=control(pressure,width,angle,overlap)
            base,t0=render(req,scale,False);refined,t1=render(req,scale,True)
            delta=mass(refined)/mass(base)-1
            records.append(dict(scale=scale,pressure=pressure,width=width,angle=angle,overlap=overlap,ink_delta=delta,base_seconds=t0,refined_seconds=t1))
            if width==20 and pressure in [64,128,255]:
                samples.append((f'{scale}x / pressure {pressure}',base,refined))
    print('Completed scale',scale,flush=True)

# Show each resolution at the same magnification of source coordinates.
contact=Image.new('RGB',(3*384, len(samples)*148),'#f8f7f3')
draw=ImageDraw.Draw(contact)
for row,(label,base,refined) in enumerate(samples):
    draw.text((8,row*148+8),label,fill='black')
    for col,(name,img) in enumerate([('Calibrated',base),('Refined (experimental)',refined)]):
        s=img.width/128
        detail=img.crop(tuple(round(v*s) for v in [44,52,84,76])).resize((320,96),Image.Resampling.NEAREST)
        x=180+col*460;contact.paste(detail,(x,row*148+32));draw.text((x,row*148+8),name,fill='black')
contact.save(OUT/'pressure-comparison.png')
private=ROOT/'artifacts/rust-renderer/private/natural-portrait.json'
if private.exists():
    req=json.loads(private.read_text(encoding='utf8'))
    # Shaded forehead detail. Translate the source, preserving all strokes and overlap.
    req['page']['paper_size']=[192,192]
    for stroke in req['page']['strokes']:
        for p in stroke['points']: p['x']-=480;p['y']-=600
    natural=Image.new('RGB',(1152,2*424),'#f8f7f3');draw=ImageDraw.Draw(natural)
    for row,scale in enumerate([2,4]):
        base,t0=render(req,scale,False);refined,t1=render(req,scale,True)
        records.append(dict(scene='portrait crop',scale=scale,ink_delta=mass(refined)/mass(base)-1,base_seconds=t0,refined_seconds=t1))
        for col,(name,img) in enumerate([('Calibrated',base),('Refined (experimental)',refined)]):
            img.save(OUT/f'portrait-{scale}x-{col}.png')
            # Enlarge a fixed 96-source-unit detail, never smooth away the grid.
            detail=img.crop((0,0,96*scale,96*scale)).resize((384,384),Image.Resampling.NEAREST)
            natural.paste(detail,(col*576,row*424+32));draw.text((col*576+8,row*424+8),f'{name} / {scale}x',fill='black')
    natural.save(OUT/'portrait-comparison.png')
(OUT/'metrics.json').write_text(json.dumps(records,indent=2),encoding='utf8')
print('Worst control density delta:',max(abs(r['ink_delta']) for r in records if 'scene' not in r))
print('Natural:',[r for r in records if 'scene' in r])
