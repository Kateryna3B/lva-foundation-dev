"""Bounded, non-executing XLSX form reader using standard library OOXML."""
from datetime import datetime,date,time,timedelta,timezone
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
import json,re,zipfile
from xml.etree import ElementTree as ET
from pathlib import Path

FIELDS=['requester_mode','requester_id','requester_alias','requester_note',
        'respondent_mode','respondent_id','respondent_alias','respondent_note',
        'conversation_date','conversation_time','timezone','utc_offset_minutes',
        'received_date','channel_scheme','language','topic1','topic2','topic3',
        'external_group_id','external_part_number','reported_offset_seconds','notes']
NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def read_form(path):
    if Path(path).stat().st_size>5*1024*1024:raise ValueError('Бланк перевищує 5 MiB')
    with zipfile.ZipFile(path) as z:
        if sum(i.file_size for i in z.infolist())>20*1024*1024:raise ValueError('Надто великий XLSX вміст')
        if any('vbaProject' in n or 'externalLink' in n for n in z.namelist()):
            raise ValueError('Макроси й зовнішні посилання в бланку заборонені')
        def xml(name):
            raw=z.read(name)
            if b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:raise ValueError('XML entities заборонені')
            return ET.fromstring(raw)
        workbook=xml('xl/workbook.xml');rels=xml('xl/_rels/workbook.xml.rels')
        targets={r.attrib['Id']:r.attrib['Target'] for r in rels}
        paths={s.attrib['name']:targets[s.attrib['{'+REL+'}id']] for s in workbook.findall('s:sheets/s:sheet',NS)}
        for required in ('Intake','Schema'):
            if required not in paths:raise ValueError('Невідомий бланк: потрібні Intake та Schema')
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            strings=[''.join(t.text or '' for t in x.findall('.//s:t',NS)) for x in xml('xl/sharedStrings.xml').findall('s:si',NS)]
        def cells(sheet):
            target=paths[sheet]
            if target.startswith('/'):target=target[1:]
            elif not target.startswith('xl/'):target='xl/'+target
            if '..' in target.split('/'):raise ValueError('Недопустимий worksheet path')
            root=xml(target);result={}
            for c in root.findall('.//s:sheetData/s:row/s:c',NS):
                if c.find('s:f',NS) is not None:raise ValueError('Формули у бланку не виконуються і не приймаються')
                kind=c.attrib.get('t');v=c.find('s:v',NS)
                if kind=='inlineStr':value=''.join(t.text or '' for t in c.findall('.//s:t',NS))
                elif kind=='s':value=strings[int(v.text)] if v is not None else ''
                else:value=v.text if v is not None and v.text is not None else ''
                result[c.attrib['r']]=value
            return result
        schema=cells('Schema')
        if schema.get('B2')!='1.0':raise ValueError('Невідома версія Excel-бланка')
        values=cells('Intake');data={}
        for row,key in enumerate(FIELDS,6):
            if values.get('A'+str(row))!=key:raise ValueError('Змінено структуру полів бланка')
            value=values.get('C'+str(row),'').strip()
            data[key]=value if value else None
    # Dates and times authored as numeric Excel values or explicit ISO strings.
    for key in ['conversation_date','received_date']:
        if data[key] and re.fullmatch(r'\d+(?:\.\d+)?',data[key]):
            data[key]=(datetime(1899,12,30)+timedelta(days=float(data[key]))).date().isoformat()
    v=data['conversation_time']
    if v and re.fullmatch(r'0(?:\.\d+)?',v):
        seconds=round(float(v)*86400)
        if seconds>=86400:raise ValueError('Час не може округлюватися до наступної доби')
        data['conversation_time']=f'{seconds//3600:02}:{seconds%3600//60:02}:{seconds%60:02}'
    return validate(data)


def validate(data):
    d={key:data.get(key) for key in FIELDS}
    for key in ['requester_mode','respondent_mode','conversation_date','conversation_time','timezone','received_date','channel_scheme','topic1']:
        if not d[key]:raise ValueError('Не заповнено '+key)
    for who in ['requester','respondent']:
        mode=d[who+'_mode']
        if mode not in ['new','select']:raise ValueError('Режим особи має бути new або select')
        if mode=='new':
            alias=d[who+'_alias']
            label='Псевдонім замовника' if who=='requester' else 'Псевдонім респондента'
            cell='C8' if who=='requester' else 'C12'
            field=who+'_alias'
            prefix=f'{label} — Intake!{cell} ({field})'
            if not alias:
                raise ValueError(prefix+': поле порожнє у збереженому бланку. Для new введіть 1–40 літер A–Z або a–z та збережіть Excel-файл.')
            if not isinstance(alias,str):
                raise ValueError(prefix+': потрібне текстове значення з 1–40 літер A–Z або a–z.')
            if len(alias)>40:
                raise ValueError(prefix+f': {len(alias)} символів; максимально 40.')
            bad=next(((i,c) for i,c in enumerate(alias,1) if not ('A'<=c<='Z' or 'a'<=c<='z')),None)
            if bad:
                position,char=bad
                raise ValueError(prefix+f': недопустимий символ у позиції {position} (U+{ord(char):04X}). Дозволені лише A–Z та a–z, без цифр, пробілів, розділових знаків і кирилиці. Виправте та збережіть Excel-файл перед повторним прийманням.')
            if d[who+'_id']:raise ValueError('Для new залиште поле ID порожнім')
        elif not d[who+'_id']:raise ValueError('Для select потрібен person_id')
    if d['channel_scheme'] not in ['interviewer_1_respondent_2','respondent_1_interviewer_2','mixed','unknown']:
        raise ValueError('Невідома схема каналів')
    if d['language'] not in [None,'auto','uk','ru','be','az','kk','et']:raise ValueError('Невідома мова')
    local_date=date.fromisoformat(d['conversation_date']);received=date.fromisoformat(d['received_date'])
    if received<local_date:raise ValueError('Дата отримання раніша за дату бесіди')
    local_time=time.fromisoformat(d['conversation_time'])
    if local_time.tzinfo is not None:raise ValueError('Час має бути місцевим, пояс задайте окремо')
    try:zone=ZoneInfo(d['timezone'])
    except ZoneInfoNotFoundError as e:raise ValueError('Пояс не знайдено: на Windows потрібна встановлена IANA база tzdata') from e
    naive=datetime.combine(local_date,local_time);candidates=[]
    for fold in [0,1]:
        aware=naive.replace(tzinfo=zone,fold=fold)
        if aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)==naive and not any(x.utcoffset()==aware.utcoffset() for x in candidates):
            candidates.append(aware)
    if not candidates:raise ValueError('Такий місцевий час не існує через перехід сезонного часу')
    if d['utc_offset_minutes'] is not None:
        offset=int(d['utc_offset_minutes']);candidates=[x for x in candidates if x.utcoffset().total_seconds()==offset*60]
        if not candidates:raise ValueError('UTC offset не відповідає цьому часовому поясу і даті')
    if len(candidates)!=1:raise ValueError('Неоднозначний місцевий час: вкажіть utc_offset_minutes')
    d['started_at_local']=candidates[0].isoformat();d['started_at_utc']=candidates[0].astimezone(timezone.utc).isoformat()
    d['time_precision']='second' if local_time.microsecond==0 else 'fractional_second'
    if d['reported_offset_seconds'] is not None:
        from decimal import Decimal,InvalidOperation
        try:v=Decimal(str(d['reported_offset_seconds']))
        except InvalidOperation as e:raise ValueError('Некоректне повідомлене зміщення') from e
        if not v.is_finite() or v<0:raise ValueError('Повідомлене зміщення має бути скінченним і невід’ємним')
        d['reported_offset_seconds']=str(v)
    if d['external_part_number'] is not None and (not str(d['external_part_number']).isdigit() or int(d['external_part_number'])<1):
        raise ValueError('Номер зовнішньої частини має бути додатним цілим')
    return d
