"""Small local launcher; work runs in a background thread, UI remains responsive."""
import sys,json,threading,queue,shutil,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'vendor'))
import tkinter as tk
from tkinter import filedialog,messagebox,simpledialog
from lva_system import __version__
from lva_system.core import Store
from lva_system import audio,time_input
from lva_system.backup_check import verify_backup

root=tk.Tk();root.title(f'LVA Foundation {__version__} — пілот');root.geometry('900x650')
work=tk.StringVar();case=tk.StringVar();q=queue.Queue();busy=False

def choose_root():
    value=filedialog.askdirectory(title='Локальний робочий каталог')
    if value:work.set(value)
def run(action,on_success=None):
    global busy
    if busy:return
    if not work.get():messagebox.showerror('Каталог','Оберіть локальний робочий каталог');return
    busy=True;folder=work.get();output.insert('end','Операція виконується…\n')
    def task():
        st=None
        try:
            st=Store(folder);q.put((True,action(st),on_success))
        except Exception as e:q.put((False,str(e),None))
        finally:
            if st:st.close()
    threading.Thread(target=task,daemon=True).start()
def poll():
    global busy
    try:
        ok,result,callback=q.get_nowait();busy=False
        if isinstance(result,dict) and 'suggested_boundaries_frames' in result:
            result={k:v for k,v in result.items() if k!='suggested_boundaries_frames'}
        output.insert('end',json.dumps(result,ensure_ascii=False,indent=2)+'\n');output.see('end')
        if ok and isinstance(result,dict) and result.get('case_id'):case.set(result['case_id'])
        if not ok:messagebox.showerror('Операцію не завершено',result)
        elif callback:callback(result)
    except queue.Empty:pass
    root.after(150,poll)
def register():
    form=filedialog.askopenfilename(title='Заповнений бланк',filetypes=[('Excel','*.xlsx')])
    if not form:return
    wav=filedialog.askopenfilename(title='Оригінальний WAV',filetypes=[('WAV','*.wav')])
    if wav:run(lambda st:st.register(form,wav))
def template():
    target=filedialog.asksaveasfilename(title='Зберегти чистий бланк',defaultextension='.xlsx',initialfile='Intake_v1.xlsx')
    if target:shutil.copyfile(Path(__file__).parent/'templates'/'Intake_v1.xlsx',target)
def prepare():
    cid=case.get();ch=simpledialog.askinteger('Респондент','Після прослуховування вкажіть канал респондента: 1 або 2',minvalue=1,maxvalue=2)
    if cid and ch:run(lambda st:st.prepare(cid,ch))
def parts():
    cid=case.get()
    run(lambda st:st.parts_plan(cid),on_success=show_parts_dialog)
def show_parts_dialog(plan):
    if plan['existing_parts']:
        rows=['Частини вже створено:']+[f"{p['part_number']}: {p['start']} — {p['end']}" for p in plan['existing_parts']]
        messagebox.showinfo('Частини', '\n'.join(rows)+'\n\nЧас показано з точністю до мілісекунди. Зміна меж потребує окремої ревізії.');return
    dialog=tk.Toplevel(root);dialog.title('Межі частин');dialog.transient(root);dialog.grab_set();dialog.resizable(False,False)
    tk.Label(dialog,text=f"Тривалість: {plan['duration']}. Частин: {plan['part_count']}.",anchor='w').pack(fill='x',padx=18,pady=(15,5))
    tk.Label(dialog,text='Введіть лише внутрішні межі: MM:SS або MM:SS.mmm.\nНаприклад 16:10.400 або 16:10,400.\nПочаток і кінець запису програма додає автоматично.',justify='left').pack(anchor='w',padx=18,pady=5)
    entries=[]
    for i,suggested in enumerate(plan['suggested_internal_times'],1):
        row=tk.Frame(dialog);row.pack(fill='x',padx=18,pady=5)
        tk.Label(row,text=f'Межа {i}:',width=12,anchor='w').pack(side='left')
        entry=tk.Entry(row,width=24);entry.insert(0,suggested);entry.pack(side='left');entries.append(entry)
    if entries:
        tk.Label(dialog,text='Запропоновані рівні межі перевірте за аудіо й за потреби змініть.',justify='left').pack(anchor='w',padx=18,pady=5)
    else:tk.Label(dialog,text='Для однієї частини внутрішні межі не потрібні.').pack(anchor='w',padx=18,pady=5)
    confirmed=tk.BooleanVar(value=False)
    if entries:tk.Checkbutton(dialog,text='Я перевірив межі за аудіо',variable=confirmed).pack(anchor='w',padx=18,pady=5)
    def submit():
        if entries and not confirmed.get():messagebox.showerror('Межі','Підтвердьте перевірку меж за аудіо',parent=dialog);return
        values=[entry.get().strip() for entry in entries]
        try:
            for value in values:time_input.parse_time_ms(value)
        except ValueError as e:messagebox.showerror('Межі',str(e),parent=dialog);return
        if busy:return
        dialog.destroy();run(lambda st:st.parts_at_times(plan['case_id'],values))
    buttons=tk.Frame(dialog);buttons.pack(fill='x',padx=18,pady=15)
    tk.Button(buttons,text='Створити частини',command=submit).pack(side='left')
    tk.Button(buttons,text='Скасувати',command=dialog.destroy).pack(side='right')
    if entries:entries[0].focus_set()
def import_lva():
    cid=case.get();part=simpledialog.askstring('Область LVA','ID частини з manifest.json.\nДля старого аналізу повного запису введіть LEGACY_FULL.')
    if not part:return
    wav=filedialog.askopenfilename(title='Саме той WAV, який аналізувався у LVA',filetypes=[('WAV','*.wav')])
    if not wav:return
    csv=filedialog.askopenfilename(title='Експорт CSV з LVA',filetypes=[('CSV','*.csv')])
    if csv:run(lambda st:st.import_lva(cid,wav,csv,None if part=='LEGACY_FULL' else part,part=='LEGACY_FULL'))
def verify():
    cid=case.get();run(lambda st:st.verify(cid))
def backup():
    dest=filedialog.askdirectory(title='Каталог резервної копії поза робочим каталогом')
    if dest:run(lambda st:st.backup(dest))
def check_backup():
    folder=filedialog.askdirectory(title='Оберіть конкретний backup_… з COMPLETE.json')
    if folder:run(lambda st:verify_backup(folder))
def open_asr():
    if busy:messagebox.showinfo('ASR','Дочекайтеся завершення поточної операції');return
    if not work.get() or not case.get():messagebox.showerror('ASR','Оберіть робочий каталог і справу');return
    subprocess.Popen([sys.executable,str(Path(__file__).resolve().parent/'Start_ASR.py'),'--root',work.get(),'--case',case.get()])
def close():
    if busy:messagebox.showinfo('Операція триває','Дочекайтеся завершення операції');return
    root.destroy()
root.protocol('WM_DELETE_WINDOW',close)
tk.Label(root,text='Робочий каталог').pack(anchor='w');tk.Entry(root,textvariable=work,width=110).pack(fill='x')
tk.Button(root,text='Обрати каталог',command=choose_root).pack(anchor='w')
tk.Label(root,text='ID справи').pack(anchor='w');tk.Entry(root,textvariable=case,width=110).pack(fill='x')
bar=tk.Frame(root);bar.pack(fill='x')
for i,(title,action) in enumerate([('Чистий бланк',template),('Приймання',register),('Витягнути канали',prepare),('Частини',parts),('Імпорт LVA',import_lva),('Транскрибація',open_asr),('Перевірити',verify),('Резервувати',backup),('Відновити',lambda:run(lambda st:st.recover())),('Справи',lambda:run(lambda st:[dict(r) for r in st.db.execute('SELECT id,code FROM cases')])),('Особи',lambda:run(lambda st:[dict(r) for r in st.db.execute('SELECT id,alias FROM people')])),('Перевірити копію',check_backup)]):
    tk.Button(bar,text=title,command=action).grid(row=i//5,column=i%5,sticky='ew')
output=tk.Text(root,wrap='word');output.pack(fill='both',expand=True);root.after(150,poll);root.mainloop()
