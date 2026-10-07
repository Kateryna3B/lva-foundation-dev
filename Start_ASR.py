"""Local ASR GUI with separate reference engine and short speech test."""
import argparse,json,os,queue,threading,time,tkinter as tk
from pathlib import Path
from tkinter import filedialog,messagebox,ttk
from lva_system import __version__
from lva_system.core import Store,uid
from lva_system.asr import transcribe_case
from lva_system.whisperx_setup import prepare_existing
from lva_system.time_input import parse_time_ms

p=argparse.ArgumentParser();p.add_argument('--root',default='');p.add_argument('--case',default='');args=p.parse_args()
base=Path(__file__).resolve().parent
settings=json.loads((base/'ASR_SETTINGS.json').read_text(encoding='utf-8'))
root=tk.Tk();root.title(f'LVA ASR {__version__} — чернетка');root.geometry('950x720')
folder=tk.StringVar(value=args.root);cid=tk.StringVar(value=args.case)
engine=tk.StringVar(value=settings.get('engine','whisperx'));python_path=tk.StringVar(value=settings.get('whisperx_python','C:/WhisperX/venv/Scripts/python.exe'))
device=tk.StringVar(value='cpu');language=tk.StringVar(value=settings.get('language','auto'))
policy=tk.StringVar(value='keep_asr');short=tk.BooleanVar(value=False);fresh=tk.BooleanVar(value=False)
start_time=tk.StringVar(value='00:00');end_time=tk.StringVar(value='01:00');status=tk.StringVar(value='Готовий: весь файл, обидва канали')
events=queue.Queue();cancel=threading.Event();busy=False;last_text=None
started_at=0;stage_at=0;last_event=None
activity=tk.StringVar();scope_hint=tk.StringVar()
STAGES={'PROCESS_STARTING':'Запуск рушія','MODEL_LOADING':'Завантаження моделі','ASR_RUNNING':'Розпізнавання мовлення','ALIGNMENT_LOADING':'Завантаження alignment','ALIGNMENT_RUNNING':'Уточнення часових меж','DONE':'Канал оброблено'}

def update_scope(*args):
    state='normal' if short.get() and not busy else 'disabled'
    start_entry.configure(state=state);end_entry.configure(state=state)
    scope_hint.set('Фрагмент: вкажіть початок і кінець (до 2 хвилин).' if short.get() else 'Весь файл, обидва канали. Початок і кінець не потрібні та ігноруються.')

def stop():
    if busy:
        cancel.set();status.set('Запит зупинки надіслано. Очікування завершення поточного етапу…')

def tick():
    if busy:
        elapsed=int(time.monotonic()-started_at);quiet=int(time.monotonic()-stage_at)
        activity.set(f'Минуло {elapsed//60:02d}:{elapsed%60:02d} | без зміни етапу {quiet//60:02d}:{quiet%60:02d}. Інтерфейс відповідає.')
    root.after(1000,tick)

def choose():
    if busy:return
    chosen=filedialog.askdirectory(title='Ваш початковий робочий каталог LVA')
    if chosen:folder.set(chosen)
def change_engine(event=None):
    if engine.get()=='whisperx':python_path.set(settings.get('whisperx_python','C:/WhisperX/venv/Scripts/python.exe'));device.set('cpu')
    else:python_path.set(str(base/'.venv_asr'/'Scripts'/'python.exe'));device.set(settings.get('device','cuda'));short.set(False)
def start():
    global busy,started_at,stage_at,last_event,last_text
    if busy:return
    if not folder.get() or not cid.get():messagebox.showerror('Дані','Оберіть робочий каталог і справу');return
    if not (Path(folder.get())/'registry.sqlite3').is_file():messagebox.showerror('Реєстр','У каталозі немає registry.sqlite3. Оберіть ваш наявний робочий каталог.');return
    python=Path(python_path.get())
    if not python.is_file():messagebox.showerror('Python','Не знайдено обраний Python. Для WhisperX потрібен ваш наявний venv.');return
    interval=None
    if short.get():
        try:
            a,b=parse_time_ms(start_time.get()),parse_time_ms(end_time.get())
            if not 0<=a<b or b-a>120000:raise ValueError('Проба має тривати від 0 до 2 хвилин; кінець після початку')
            interval=(start_time.get().strip(),end_time.get().strip())
        except ValueError as e:messagebox.showerror('Час',str(e));return
    if engine.get()=='whisperx' and device.get()!='cpu':messagebox.showerror('Профіль','Контрольний WhisperX-профіль цього випуску тільки CPU');return
    if interval and engine.get()!='whisperx':messagebox.showerror('Профіль','Коротка проба доступна для WhisperX');return
    values={'root':folder.get(),'cid':cid.get(),'engine':engine.get(),'device':device.get(),'language':None if language.get()=='auto' else language.get(),'alignment_policy':policy.get(),'interval_times':interval,'revision_token':uid() if fresh.get() else None}
    scope='короткий фрагмент' if interval else 'повні канали'
    if not messagebox.askokcancel('Локальний запуск',f'Будуть розпізнані обидва канали: {scope}. Результат — чернетка. Під час запуску не виконуйте іншу транскрибацію чи резервування цього реєстру.'):return
    busy=True;started_at=stage_at=time.monotonic();last_event=None;last_text=None;cancel.clear();start_button.configure(state='disabled');short_button.configure(state='disabled');stop_button.configure(state='normal');update_scope();bar.start(15);status.set('Перевірка кешу і хешів моделі…');log.insert('end','Операція почалася. Пакети та моделі не завантажуються.\n')
    def task():
        st=None
        try:
            descriptor=base/'models'/('whisperx_reference' if values['engine']=='whisperx' else 'large-v3')
            if values['engine']=='whisperx':prepare_existing(python,descriptor)
            if cancel.is_set():raise InterruptedError('Зупинено після перевірки кешу')
            events.put(('progress',{'state':'Перевірка джерел і підготовка запуску'}))
            st=Store(values['root'])
            result=transcribe_case(st,values['cid'],descriptor,python,device=values['device'],language=values['language'],engine=values['engine'],alignment_policy=values['alignment_policy'],interval_times=values['interval_times'],revision_token=values['revision_token'],cancel=cancel,progress=lambda d:events.put(('progress',d)),dll_dirs=settings.get('dll_dirs',[]))
            events.put(('done',result))
        except Exception as e:events.put(('error',str(e)))
        finally:
            if st:st.close()
    threading.Thread(target=task,daemon=True).start()
def poll():
    global busy,last_text,last_event,stage_at
    try:
        while True:
            kind,data=events.get_nowait()
            if kind=='progress':
                signature=(data.get('role'),data.get('state'),data.get('segments'),data.get('processed_us'))
                stage=STAGES.get(data.get('state'),data.get('state','Очікування'))
                role={'interviewer':'Інтерв’юер','respondent':'Респондент'}.get(data.get('role'),data.get('role',''))
                message=f"{role}: {stage}".strip(': ')
                if data.get('process_alive'):message+=f" | процес PID {data['pid']} працює"
                if signature!=last_event:
                    last_event=signature;stage_at=time.monotonic()
                    log.insert('end',time.strftime('%H:%M:%S')+' '+message+'\n');log.see('end')
                    if data.get('log_path'):log.insert('end','Журнал рушія: '+data['log_path']+'\n')
                if not cancel.is_set():status.set(message)
            else:
                busy=False;bar.stop();start_button.configure(state='normal');short_button.configure(state='normal');stop_button.configure(state='disabled');update_scope()
                elapsed=int(time.monotonic()-started_at);activity.set(f'Завершено через {elapsed//60:02d}:{elapsed%60:02d}')
                status.set('Чернетку збережено — перевірте текст і статус alignment' if kind=='done' else 'Операцію не завершено')
                log.insert('end',json.dumps(data,ensure_ascii=False,indent=2)+'\n');log.see('end')
                if kind=='done':
                    last_text=next((f for f in data.get('review_files',[]) if f.endswith('.txt')),None)
                    if any(w.startswith('ALIGNMENT_FAILED:') for w in data.get('warnings',[])):messagebox.showwarning('Alignment не виконано','Текст збережено з ASR_ESTIMATED. Час не підтверджений; перегляньте channel_statuses.')
                else:messagebox.showerror('ASR',str(data))
    except queue.Empty:pass
    root.after(250,poll)
def open_text():
    if last_text:os.startfile(last_text)
    else:messagebox.showinfo('Текст','Спочатку створіть нову чернетку. Попередні експорти доступні через manifest справи.')
def close():
    if busy:messagebox.showinfo('Операція','Натисніть «Зупинити» й дочекайтеся завершення. Перевірка кешу зупиняється після завершення її поточного етапу.');return
    root.destroy()

def label(text):tk.Label(root,text=text).pack(anchor='w')
label('Робочий каталог');tk.Entry(root,textvariable=folder).pack(fill='x');tk.Button(root,text='Обрати каталог',command=choose).pack(anchor='w')
label('ID справи');tk.Entry(root,textvariable=cid).pack(fill='x')
label('Рушій');combo=ttk.Combobox(root,textvariable=engine,values=['whisperx','faster-whisper'],state='readonly');combo.pack(anchor='w');combo.bind('<<ComboboxSelected>>',change_engine)
label('Python рушія');tk.Entry(root,textvariable=python_path).pack(fill='x')
row=tk.Frame(root);row.pack(fill='x');tk.Label(row,text='Пристрій').pack(side='left');ttk.Combobox(row,textvariable=device,values=['cpu','cuda'],state='readonly',width=10).pack(side='left');tk.Label(row,text='Мова').pack(side='left');ttk.Combobox(row,textvariable=language,values=['auto','uk','ru','be','az','kk','et'],state='readonly',width=10).pack(side='left')
label('Alignment: keep_asr — зберегти текст із явним fallback; require — вимагати alignment');ttk.Combobox(root,textvariable=policy,values=['keep_asr','require'],state='readonly').pack(anchor='w')
short_button=tk.Checkbutton(root,text='Коротка проба обох каналів (не більше 2 хвилин)',variable=short);short_button.pack(anchor='w')
row=tk.Frame(root);row.pack(fill='x');tk.Label(row,text='Початок MM:SS.mmm').pack(side='left');start_entry=tk.Entry(row,textvariable=start_time,width=16);start_entry.pack(side='left');tk.Label(row,text='Кінець MM:SS.mmm').pack(side='left');end_entry=tk.Entry(row,textvariable=end_time,width=16);end_entry.pack(side='left')
tk.Label(root,textvariable=scope_hint).pack(anchor='w');short.trace_add('write',update_scope);update_scope()
tk.Checkbutton(root,text='Нова ревізія: розпізнати заново, зберігши попередню чернетку',variable=fresh).pack(anchor='w')
buttons=tk.Frame(root);buttons.pack(fill='x');start_button=tk.Button(buttons,text='Запустити',command=start);start_button.pack(side='left');stop_button=tk.Button(buttons,text='Зупинити',command=stop,state='disabled');stop_button.pack(side='left');tk.Button(buttons,text='Відкрити текст',command=open_text).pack(side='left')
tk.Label(root,textvariable=status).pack(anchor='w');tk.Label(root,textvariable=activity).pack(anchor='w')
bar=ttk.Progressbar(root,mode='indeterminate');bar.pack(fill='x')
tk.Label(root,text='Рух індикатора означає очікування; відсоток готовності рушій не повідомляє.').pack(anchor='w')
log=tk.Text(root,wrap='word');log.pack(fill='both',expand=True)
root.protocol('WM_DELETE_WINDOW',close);root.after(250,poll);root.after(1000,tick);root.mainloop()
