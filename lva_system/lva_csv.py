"""Strict observed CSV adapter. Raw fields retained; time meaning stays unverified."""
import csv,io,re
HEADER=['No.','Issue','Start','End','Textual Analysis','SPT','SPJ','JQ','AVJ (x100)','SOS (x100)','FMain','FX','FQ (x100)','FFlic','LieStress','LieProb','CogStress','EmoStress','GlbStress','FRGstress','Anticipation','ThinkingRate','SUBcog','SUBemo','FJQ','SAF']
PROFILE='lva650_csv_observed_26_v1'

def candidate_time(raw,prefix):
    match=re.fullmatch(r'\s*'+prefix+r'\s+(\d+):([0-5]\d):(\d{3})\s*',raw)
    if not match:raise ValueError('Невідомий синтаксис часу LVA')
    m,s,ms=map(int,match.groups());return (m*60000+s*1000+ms)*1000

def parse(raw,encoding='utf-8-sig'):
    if len(raw)>32*1024*1024:raise ValueError('Надто великий CSV')
    records=list(csv.reader(io.StringIO(raw.decode(encoding),newline='')))
    start=next((i for i,r in enumerate(records) if r and r[0].strip()=='No.'),None)
    if start is None:raise ValueError('Заголовок LVA не знайдено')
    header=[x.strip() for x in records[start]]
    if len(header)==27 and header[-1]=='':header=header[:-1]
    if header!=HEADER:raise ValueError('Невідома схема колонок LVA; автоматичного наближеного імпорту немає')
    seen=set();segments=[]
    for line,row in enumerate(records[start+1:],start+2):
        if not row or not any(x.strip() for x in row):continue
        if len(row)!=26:raise ValueError('Невідповідна кількість колонок у рядку '+str(line))
        number=row[0].strip()
        if not number or number in seen:raise ValueError('Порожній або повторений номер сегмента')
        seen.add(number);a=candidate_time(row[2],'S');b=candidate_time(row[3],'E')
        if a>=b:raise ValueError('Неправильний інтервал сегмента '+number)
        metrics=[]
        for name,value in zip(HEADER[5:],row[5:]):
            stripped=value.strip();state='missing' if not stripped else 'valid' if re.fullmatch(r'[+-]?\d+',stripped) else 'parse_error'
            metrics.append(dict(name_raw=name,raw_value=value,value_state=state,parsed_number=int(stripped) if state=='valid' else None))
        segments.append(dict(external_no=number,source_row=line,raw_fields=dict(zip(HEADER,row)),candidate_start_us=a,candidate_end_us=b,metrics=metrics))
    if not segments:raise ValueError('CSV без сегментів')
    return dict(schema_version='1.0',profile_id=PROFILE,time_status='UNVERIFIED',raw_preamble=records[:start],segments=segments)
