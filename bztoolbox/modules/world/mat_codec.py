from __future__ import annotations
import math, os, re
from dataclasses import dataclass
import numpy as np
from PIL import Image, ImageDraw

MAT_ZONE_SIZE=64
MAT_ENTRY_BYTES=2
HG2_SAMPLES_PER_ZONE=256
MAKE_TRN_SAMPLE_STEP=4
MAKE_TRN_LAYER_LIMIT=8
MAKE_TRN_ELEVATION_DIVISOR=5
MAKE_TRN_DEGREES_PER_RADIAN=57.295780181884766
PAINTER_MAX_MATERIAL=7
PAINTER_MAX_ELEVATION=4095.0
PAINTER_MAX_ELEVATION_DM=PAINTER_MAX_ELEVATION
WORLD_ZONE_METERS=1280.0

@dataclass(frozen=True)
class MatEntry:
    base:int; next:int; cap:int; flip:int; rotation:int; variant:int
    @property
    def mix(self): return ((self.cap&1)<<3)|((self.flip&1)<<2)|(self.rotation&3)
    @property
    def documented_variant(self): return self.variant&3
    @property
    def reserved(self): return (self.variant>>2)&3

@dataclass
class PaintStats:
    total_tiles:int=0; solid_tiles:int=0; cap_tiles:int=0; diagonal_tiles:int=0
    ambiguous_tiles:int=0; unsupported_transition_tiles:int=0; unmatched_samples:int=0

@dataclass(frozen=True)
class TRNPainterConfig:
    layers:tuple; texture_types:tuple; cap_transitions:frozenset; diagonal_transitions:frozenset
    min_x:float=0.; min_z:float=0.; width:float|None=None; depth:float|None=None
    @property
    def transitions(self): return self.cap_transitions|self.diagonal_transitions

class MakeTRNRuleError(ValueError):
    def __init__(self,x,z,elevation,slope):
        super().__init__(f"MakeTRN-compatible painter found no valid layer at x={x}, z={z}: elevation={elevation}, slope={slope}")
        self.x=x; self.z=z; self.elevation=elevation; self.slope=slope

class MSVCRand:
    def __init__(self,seed=1): self.state=int(seed)&0xffffffff
    def rand(self):
        self.state=(self.state*214013+2531011)&0xffffffff
        return (self.state>>16)&0x7fff

def _range(name,v,lo,hi):
    if not lo<=int(v)<=hi: raise ValueError(f"{name} must be in {lo}..{hi}, got {v}")

def encode_entry(base,next_mat,cap=0,flip=0,rotation=0,variant=0,reserved=None):
    for n,v,lo,hi in (("base",base,0,15),("next_mat",next_mat,0,15),("cap",cap,0,1),("flip",flip,0,1),("rotation",rotation,0,3)): _range(n,v,lo,hi)
    if reserved is None: _range("variant",variant,0,15); low=int(variant)&15
    else: _range("variant",variant,0,3); _range("reserved",reserved,0,3); low=(int(variant)&3)|((int(reserved)&3)<<2)
    mix=((int(cap)&1)<<3)|((int(flip)&1)<<2)|(int(rotation)&3)
    return low|((mix&15)<<4)|((int(next_mat)&15)<<8)|((int(base)&15)<<12)

def encode_mix_entry(base,next_mat,mix,variant=0):
    _range("mix",mix,0,15); return encode_entry(base,next_mat,(mix>>3)&1,(mix>>2)&1,mix&3,variant)

def decode_entry(value):
    _range("MAT entry",value,0,0xffff); mix=(int(value)>>4)&15
    return MatEntry((value>>12)&15,(value>>8)&15,(mix>>3)&1,(mix>>2)&1,mix&3,value&15)

def entry_to_bytes(value): _range("MAT entry",value,0,0xffff); return int(value).to_bytes(2,"little")
def entry_from_bytes(raw):
    if len(raw)!=2: raise ValueError("A MAT entry is exactly two bytes")
    return int.from_bytes(raw,"little")
def expected_mat_bytes(zx,zz):
    if zx<=0 or zz<=0: raise ValueError("MAT zone dimensions must be positive")
    return zx*zz*MAT_ZONE_SIZE*MAT_ZONE_SIZE*2

def pack_mat_zones(entries,zx,zz):
    a=np.asarray(entries); shape=(zz*64,zx*64)
    if a.shape!=shape: raise ValueError(f"MAT shape {a.shape} does not match {shape}")
    a=np.rint(a).astype("<u2"); out=bytearray(expected_mat_bytes(zx,zz)); p=0
    for z in range(zz):
        for x in range(zx):
            raw=a[z*64:(z+1)*64,x*64:(x+1)*64].tobytes(order="C"); out[p:p+8192]=raw; p+=8192
    return bytes(out)

def unpack_mat_zones(payload,zx,zz):
    if len(payload)!=expected_mat_bytes(zx,zz): raise ValueError("MAT size mismatch")
    raw=np.frombuffer(payload,dtype="<u2"); out=np.empty((zz*64,zx*64),np.uint16); p=0
    for z in range(zz):
        for x in range(zx): out[z*64:(z+1)*64,x*64:(x+1)*64]=raw[p:p+4096].reshape(64,64); p+=4096
    return out

def write_mat(path,entries,zx,zz):
    with open(path,"wb") as f: f.write(pack_mat_zones(entries,zx,zz))
def read_mat(path,zx,zz):
    with open(path,"rb") as f: return unpack_mat_zones(f.read(),zx,zz)

def _num(v):
    m=re.search(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?",v)
    if not m: raise ValueError(v)
    return float(m.group())
def _iv(v,d):
    try:return int(_num(v))
    except:return d

def parse_trn_painter(path):
    sec={}; cur=""
    with open(path,"r",encoding="cp1252",errors="replace") as f:
        for s in f:
            s=s.strip()
            if not s or s.startswith(("//",";")): continue
            if s.startswith("[") and s.endswith("]"): cur=s[1:-1].strip(); sec.setdefault(cur,[]); continue
            if "=" in s and cur: k,v=s.split("=",1); sec[cur].append((k.strip(),v.strip()))
    size={"minx":0.,"minz":0.,"width":None,"depth":None}; types=set(); caps=set(); diags=set(); layers=[]
    for name,items in sec.items():
        low=name.lower(); vals={k.lower():v for k,v in items}
        if low=="size":
            for k in size:
                if k in vals:
                    try:size[k]=_num(vals[k])
                    except:pass
            continue
        m=re.fullmatch(r"texturetype(\d+)",low)
        if m:
            b=int(m.group(1)); types.add(b)
            for k,_ in items:
                c=re.match(r"capto(\d+)_",k,re.I); d=re.match(r"diagonalto(\d+)_",k,re.I)
                if c:caps.add((b,int(c.group(1))))
                if d:diags.add((b,int(d.group(1))))
            continue
        m=re.fullmatch(r"layer(\d+)",low)
        if m and int(m.group(1))<8:
            mat=_iv(vals.get("material","8"),8)
            if mat<8: layers.append((int(m.group(1)),{"mat_id":mat,"min_h":_iv(vals.get("elevationstart","4095"),4095),"max_h":_iv(vals.get("elevationend","4095"),4095),"min_s":_iv(vals.get("slopestart","90"),90),"max_s":_iv(vals.get("slopeend","90"),90),"mask_path":""}))
    layers.sort()
    return TRNPainterConfig(tuple(v for _,v in layers),tuple(sorted(types)),frozenset(caps),frozenset(diags),float(size["minx"] or 0),float(size["minz"] or 0),size["width"],size["depth"])

def default_make_trn_rules():
    return [{"mat_id":0,"min_h":0,"max_h":4095,"min_s":0,"max_s":15,"mask_path":""},{"mat_id":3,"min_h":0,"max_h":4095,"min_s":15,"max_s":90,"mask_path":""}]

def validate_paint_rules(rules):
    r=list(rules); w=[]
    if not r:return ["No paint rules are defined."]
    if len(r)>8:w.append(f"MakeTRN supports at most 8 layers; found {len(r)}")
    for i,a in enumerate(r):
        try:m=int(a["mat_id"]); h0=int(float(a["min_h"])); h1=int(float(a["max_h"])); s0=int(float(a["min_s"])); s1=int(float(a["max_s"]))
        except:w.append(f"Rule {i}: malformed numeric fields"); continue
        if not 0<=m<=7:w.append(f"Rule {i} (Mat{m}): painter material must be 0..7")
        if h0>h1:w.append(f"Rule {i} (Mat{m}): ElevationStart > ElevationEnd")
        if s0>s1:w.append(f"Rule {i} (Mat{m}): SlopeStart > SlopeEnd")
        if s0<0 or s1>90:w.append(f"Rule {i} (Mat{m}): normal MakeTRN slope range is 0..90 degrees")
        p=str(a.get("mask_path","") or "")
        if p and not p.upper().startswith("PATH:") and not os.path.exists(p):w.append(f"Rule {i} (Mat{m}): mask file does not exist: {p}")
    return w

def _sw(v): v=int(v)&0xffff; return v-0x10000 if v&0x8000 else v
def _sample(h,x,z,fallback=0): return _sw(h[z,x]) if 0<=z<h.shape[0] and 0<=x<h.shape[1] else int(fallback)
def make_trn_metrics_at(height_raw,x,z,fallback_elevation=0):
    h=np.asarray(height_raw); minimum=_sample(h,x,z,fallback_elevation); delta=0
    for dz in range(-4,4):
        for dx in range(-4,4):
            minimum=min(minimum,_sample(h,x+dx,z+dz,fallback_elevation))
            a=_sample(h,x+dx,z+dz,fallback_elevation); b=_sample(h,x+dx+1,z+dz,fallback_elevation); c=_sample(h,x+dx+1,z+dz+1,fallback_elevation); d=_sample(h,x+dx,z+dz+1,fallback_elevation)
            delta=max(delta,abs(a-b),abs(b-c),abs(c-d),abs(d-a))
    elev=math.trunc(minimum/5); slope=0 if not delta else math.trunc(math.asin(delta/math.sqrt(delta*delta+2500.0))*MAKE_TRN_DEGREES_PER_RADIAN)
    return elev,slope

def _geom(h,zx,zz):
    expected=(zz*256,zx*256)
    if np.asarray(h).shape!=expected: raise ValueError(f"MakeTRN-compatible Redux painting expects {expected[1]}x{expected[0]} HG2 samples; found {np.asarray(h).shape[1]}x{np.asarray(h).shape[0]}")
def calculate_slope_degrees(height_raw,zx,zz):
    h=np.asarray(height_raw); _geom(h,zx,zz); out=np.empty((zz*64,zx*64),np.float32)
    for z in range(out.shape[0]):
        for x in range(out.shape[1]):out[z,x]=make_trn_metrics_at(h,x*4,z*4)[1]
    return out

def _path_mask(h,w,paths,label,minx,minz,ww,wd):
    p=next((p for p in paths if p.get("label")==label),None)
    if not p or not p.get("points"):return np.zeros((h,w),bool)
    im=Image.new("L",(w,h),0); d=ImageDraw.Draw(im); pts=[((float(x)-minx)/ww*w,(float(z)-minz)/wd*h) for x,z in p["points"]]
    if p.get("type")==3 and len(pts)>=3:d.polygon(pts,fill=255)
    elif len(pts)>=2:d.line(pts,fill=255,width=max(1,round(min(h,w)/128)))
    return np.asarray(im)>127

def _masks(shape,rules,paths,minx,minz,ww,wd):
    out=[]; h,w=shape
    for r in rules:
        p=str(r.get("mask_path","") or "")
        if not p:out.append(None)
        elif p.upper().startswith("PATH:"):out.append(_path_mask(h,w,paths,p.split(":",1)[1],minx,minz,ww,wd))
        else:
            im=Image.open(p).convert("L")
            if im.size!=(w,h):im=im.resize((w,h),Image.Resampling.NEAREST)
            out.append(np.asarray(im)>127)
    return out

def classify_samples(height_raw,rules,zx,zz,bzn_paths=None,min_x=0.,min_z=0.,world_width=None,world_depth=None,fallback_elevation=0,strict=True):
    h=np.asarray(height_raw); _geom(h,zx,zz); rules=list(rules)[:8] or default_make_trn_rules(); masks=_masks(h.shape,rules,bzn_paths or [],min_x,min_z,float(world_width or zx*1280),float(world_depth or zz*1280)); out=np.zeros((zz*64,zx*64),np.uint8); unmatched=0
    for mz in range(out.shape[0]):
        for mx in range(out.shape[1]):
            x,z=mx*4,mz*4; e,s=make_trn_metrics_at(h,x,z,fallback_elevation); chosen=None
            for i,r in enumerate(rules):
                if int(float(r["min_h"]))<=e<=int(float(r["max_h"])) and int(float(r["min_s"]))<=s<=int(float(r["max_s"])) and (masks[i] is None or masks[i][z,x]): chosen=int(r["mat_id"]); break
            if chosen is None:
                unmatched+=1
                if strict:raise MakeTRNRuleError(x,z,e,s)
                chosen=0
            if not 0<=chosen<=7:raise MakeTRNRuleError(x,z,e,s)
            out[mz,mx]=chosen
    return out,unmatched

_MIX={3:0,6:1,12:2,9:3,7:8,14:9,13:10,11:11}
def _variant(r):
    n=r&15
    return 0 if n>=8 else 1 if n>=4 else 2 if n>=2 else 3
def encode_make_trn_tile(corners,rng=None):
    v=tuple(map(int,corners)); lo,hi=min(v),max(v); pattern=sum(1<<i for i,x in enumerate(v) if x!=lo); mix=_MIX.get(pattern); ambiguous=any(x not in (lo,hi) for x in v)
    if ambiguous:base=nxt=7; mix=0; kind="ambiguous"
    elif lo==hi:base=nxt=lo; mix=None; kind="solid"
    elif mix is None:base=nxt=lo; kind="ambiguous"
    else:base,nxt=lo,hi; kind="diagonal" if mix>=8 else "cap"
    rng=rng or MSVCRand(1); r=rng.rand(); mirror=(r>>2)&4; mix=((r>>13)|mirror) if base==nxt else mix|mirror
    return encode_mix_entry(base,nxt,mix,_variant(r)),kind
def encode_transition_from_corners(corners,cap_transitions=None,diagonal_transitions=None,default_material=0): return encode_make_trn_tile(corners,MSVCRand(1))
def _at(a,x,z): return int(a[z,x]) if 0<=z<a.shape[0] and 0<=x<a.shape[1] else 0

def generate_mat(height_raw,rules,zx,zz,cap_transitions=None,diagonal_transitions=None,transitions=None,bzn_paths=None,min_x=0.,min_z=0.,world_width=None,world_depth=None,default_material=0,legacy_seed=1,fallback_elevation=0,strict=True):
    warnings=validate_paint_rules(rules); fatal=[w for w in warnings if any(k in w for k in ("malformed","must be 0..7","ElevationStart >","SlopeStart >","at most","does not exist"))]
    if fatal:raise ValueError("; ".join(fatal))
    mats,unmatched=classify_samples(height_raw,rules,zx,zz,bzn_paths,min_x,min_z,world_width,world_depth,fallback_elevation,strict)
    if transitions is not None and cap_transitions is None and diagonal_transitions is None:cap_transitions=diagonal_transitions=transitions
    caps=frozenset(cap_transitions or ()); diags=frozenset(diagonal_transitions or ()); vc=cap_transitions is not None; vd=diagonal_transitions is not None
    out=np.empty((zz*64,zx*64),np.uint16); st=PaintStats(out.size,unmatched_samples=unmatched); rng=MSVCRand(legacy_seed)
    for Z in range(zz):
        for X in range(zx):
            for lz in range(64):
                z=Z*64+lz
                for lx in range(64):
                    x=X*64+lx; entry,kind=encode_make_trn_tile((_at(mats,x,z),_at(mats,x+1,z),_at(mats,x+1,z+1),_at(mats,x,z+1)),rng); out[z,x]=entry; d=decode_entry(entry)
                    if kind=="solid":st.solid_tiles+=1
                    elif kind=="cap":st.cap_tiles+=1; st.unsupported_transition_tiles+=int(vc and (d.base,d.next) not in caps)
                    elif kind=="diagonal":st.diagonal_tiles+=1; st.unsupported_transition_tiles+=int(vd and (d.base,d.next) not in diags)
                    else:st.ambiguous_tiles+=1; st.solid_tiles+=1
    return out,st
