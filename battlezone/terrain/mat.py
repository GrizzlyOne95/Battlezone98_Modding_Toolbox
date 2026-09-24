"""MAT tile material maps.

One little-endian uint16 per terrain tile, 64x64 tiles per zone, stored zone
by zone (row-major zones, each zone row-major, south first). Entry bits::

    15-12 base material   11-8 next material   7 cap   6 flip   5-4 rotation
    3-0   variant (documented: bits 0-1 variant, bits 2-3 reserved)

``mix`` is bits 7-4 (cap/flip/rotation). The MakeTRN-compatible painter that
chooses entries lives in WorldBuilder; this module is only the file format.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MAT_ZONE_SIZE=64
MAT_ENTRY_BYTES=2


@dataclass(frozen=True)
class MatEntry:
    base:int; next:int; cap:int; flip:int; rotation:int; variant:int
    @property
    def mix(self): return ((self.cap&1)<<3)|((self.flip&1)<<2)|(self.rotation&3)
    @property
    def documented_variant(self): return self.variant&3
    @property
    def reserved(self): return (self.variant>>2)&3

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
