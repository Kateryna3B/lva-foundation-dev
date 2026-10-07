"""Lossless RIFF/WAVE channel and interval operations; no DSP or float casts."""
import hashlib
import struct
from pathlib import Path

class AudioError(ValueError):
    pass


def inspect(path):
    path=Path(path)
    with path.open('rb') as f:
        head=f.read(12)
        if len(head)!=12 or head[:4]!=b'RIFF' or head[8:]!=b'WAVE':
            raise AudioError('Підтримується RIFF/WAVE; інший контейнер потребує окремого профілю')
        end=struct.unpack('<I',head[4:8])[0]+8
        if end!=path.stat().st_size:
            raise AudioError('Розмір RIFF не відповідає фактичному розміру файла')
        pos=12;fmt=None;data=None
        while pos<end:
            if pos+8>end:raise AudioError('Обрізаний заголовок WAV chunk')
            f.seek(pos);header=f.read(8);length=struct.unpack('<I',header[4:])[0]
            if pos+8+length+(length%2)>end:raise AudioError('Обрізаний WAV chunk')
            if header[:4]==b'fmt ':
                if fmt is not None or length<16 or length>65536:raise AudioError('Некоректний fmt chunk')
                fmt=f.read(length)
            elif header[:4]==b'data':
                if data is not None:raise AudioError('Кілька data chunks потребують іншого профілю')
                data=(pos+8,length)
            pos+=8+length+(length%2)
    if fmt is None or data is None:raise AudioError('Відсутній fmt або data')
    tag,channels,rate,byte_rate,align,bits=struct.unpack('<HHIIHH',fmt[:16])
    valid_bits=bits;extended=tag==65534
    if extended:
        if len(fmt)<40:raise AudioError('Обрізаний extensible fmt')
        cb,valid_bits=struct.unpack('<HH',fmt[16:20])
        if cb<22 or len(fmt)<18+cb or fmt[28:40]!=bytes.fromhex('00001000800000aa00389b71'):
            raise AudioError('Невідомий extensible GUID або довжина')
        tag=struct.unpack('<I',fmt[24:28])[0]
    widths={1:(16,24,32),3:(32,64)}
    if tag not in widths or bits not in widths[tag] or not 0<valid_bits<=bits:
        raise AudioError('Пілот підтримує PCM 16/24/32 та IEEE FLOAT 32/64')
    if channels<1 or rate<1 or align!=channels*(bits//8) or byte_rate!=rate*align or data[1]%align:
        raise AudioError('Некоректні параметри або неповний frame')
    frames=data[1]//align
    if frames<1:raise AudioError('Порожній WAV')
    return dict(sample_rate=rate,channels=channels,bits=bits,valid_bits=valid_bits,
                sample_type='PCM' if tag==1 else 'IEEE_FLOAT',frames=frames,
                duration_seconds=frames/rate,block_align=align,data_offset=data[0],
                data_bytes=data[1],format_bytes_hex=fmt.hex())


def count_parts(frames,rate):
    if frames<=rate*1200:return 1
    if frames<rate*2700:return 2
    if frames<=rate*3600:return 3
    raise AudioError('Понад 60 хв: поділіть вручну до основної обробки')


def equal_boundaries(frames,rate):
    k=count_parts(frames,rate)
    if k is None:raise AudioError('Понад 60 хв: поділіть вручну до основної обробки')
    return [i*frames//k for i in range(k)]+[frames]


def write_channel(source,destination,channel,start=0,end=None):
    info=inspect(source);end=info['frames'] if end is None else end
    if type(channel)!=int or not 1<=channel<=info['channels']:
        raise AudioError('Некоректний канал')
    if not (type(start)==int and type(end)==int and 0<=start<end<=info['frames']):
        raise AudioError('Некоректні межі в семплах')
    width=info['bits']//8;align=info['block_align'];frames=end-start
    fmt=bytearray.fromhex(info['format_bytes_hex'])
    struct.pack_into('<H',fmt,2,1);struct.pack_into('<I',fmt,8,info['sample_rate']*width)
    struct.pack_into('<H',fmt,12,width)
    if struct.unpack('<H',fmt[:2])[0]==65534:struct.pack_into('<I',fmt,20,0)
    size=frames*width
    body_size=4+8+len(fmt)+(len(fmt)%2)+8+size+(size%2)
    if body_size>0xffffffff:raise AudioError('Для такого розміру потрібен RF64; пілот його не пише')
    expected=hashlib.sha256();destination=Path(destination)
    with Path(source).open('rb') as src,destination.open('xb') as dst:
        dst.write(b'RIFF'+struct.pack('<I',body_size)+b'WAVEfmt '+struct.pack('<I',len(fmt))+fmt)
        if len(fmt)%2:dst.write(b'\0')
        dst.write(b'data'+struct.pack('<I',size));src.seek(info['data_offset']+start*align)
        remain=frames
        while remain:
            n=min(remain,65536);chunk=src.read(n*align)
            if len(chunk)!=n*align:raise AudioError('Джерело змінилось або обірвалось під час читання')
            out=bytearray(n*width)
            for byte in range(width):out[byte::width]=chunk[(channel-1)*width+byte::align]
            dst.write(out);expected.update(out);remain-=n
        if size%2:dst.write(b'\0')
        dst.flush()
        import os
        os.fsync(dst.fileno())
    actual=inspect(destination);h=hashlib.sha256()
    with destination.open('rb') as f:
        f.seek(actual['data_offset']);left=actual['data_bytes']
        while left:
            block=f.read(min(left,1048576))
            if not block:raise AudioError('Неповний вихід')
            h.update(block);left-=len(block)
    if h.hexdigest()!=expected.hexdigest() or actual['frames']!=frames:
        raise AudioError('Не пройдено перевірку семплів виходу')
    actual['sample_payload_sha256']=h.hexdigest()
    return actual
