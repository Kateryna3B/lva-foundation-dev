"""User time notation and exact integer conversion; no binary floating point."""
import re

def parse_time_ms(value):
    if not isinstance(value,str):raise ValueError('Час має бути текстом MM:SS або MM:SS.mmm')
    match=re.fullmatch(r'([0-9]{1,6}):([0-5][0-9])(?:[.,]([0-9]{1,3}))?',value.strip())
    if not match:raise ValueError('Неправильний час. Введіть MM:SS або MM:SS.mmm, наприклад 16:10.400. Кома теж дозволена.')
    minute,second,fraction=match.groups()
    return (int(minute)*60+int(second))*1000+int((fraction or '').ljust(3,'0') or '0')

def format_time(frames,rate):
    if type(frames)!=int or frames<0 or type(rate)!=int or rate<=0:raise ValueError('Некоректний час аудіо')
    ms=(2*frames*1000+rate)//(2*rate)
    return f'{ms//60000:02}:{ms//1000%60:02}.{ms%1000:03}'

def boundaries_from_times(values,frames,rate,part_count):
    if type(frames)!=int or frames<=0 or type(rate)!=int or rate<=0 or part_count not in (1,2,3):raise ValueError('Некоректні параметри поділу')
    if len(values)!=part_count-1:raise ValueError(f'Потрібно внутрішніх меж: {part_count-1}. Початок і кінець програма додає сама.')
    ms=[parse_time_ms(v) for v in values]
    if any(v<=0 or v*rate>=frames*1000 for v in ms):raise ValueError('Внутрішня межа має бути після початку й до кінця запису')
    if any(a>=b for a,b in zip(ms,ms[1:])):raise ValueError('Межі повинні йти за зростанням без повторів')
    # Nearest frame, ties toward the later frame; requested times stay recorded.
    internal=[(v*rate+500)//1000 for v in ms]
    bounds=[0,*internal,frames]
    if any(a>=b for a,b in zip(bounds,bounds[1:])):raise ValueError('Межі після перерахунку дають порожню частину. Оберіть інший час.')
    return bounds,{'input_format':'MM:SS[.mmm]','requested_internal_times':[v.strip() for v in values],'requested_internal_ms':ms,'sample_rate':rate,'conversion':'nearest_frame_half_up','boundaries_frames':bounds}
