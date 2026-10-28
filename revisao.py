"""Revisão humana auditável, vinculada ao conteúdo efetivamente conferido."""
import hashlib,json,time,re,threading
from pathlib import Path
from reunioes.core import db,read
_locks={};_gate=threading.Lock()
def revision_lock(root,mid):
    with _gate:return _locks.setdefault((str(Path(root).resolve()),mid),threading.RLock())

def signature(transcript):
    value={'engine':transcript.get('engine'),'signature':transcript.get('signature'),'segments':[{**{k:s.get(k) for k in ('start','end','text')},**({'speaker':s['speaker']} if 'speaker' in s else {})} for s in transcript.get('segments',[])],'text':transcript.get('text') if not transcript.get('segments') else None}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def init(root):
    with db(root) as c:
        c.execute('CREATE TABLE IF NOT EXISTS transcript_edits(meeting_id TEXT,base_signature TEXT,segment INTEGER,text TEXT,at REAL,PRIMARY KEY(meeting_id,base_signature,segment))')
        c.execute('CREATE TABLE IF NOT EXISTS transcript_approval(meeting_id TEXT PRIMARY KEY,signature TEXT,at REAL)')
        c.execute('CREATE TABLE IF NOT EXISTS transcript_edit_log(id INTEGER PRIMARY KEY AUTOINCREMENT,meeting_id TEXT,segment INTEGER,before_text TEXT,after_text TEXT,at REAL)')

def effective(root,mid,transcript):
    out=dict(transcript);base=signature(transcript)
    out['segments']=[dict(s) for s in transcript.get('segments',[])]
    with db(root) as c:
        rows=c.execute('SELECT segment,text FROM transcript_edits WHERE meeting_id=? AND base_signature=?',(mid,base)).fetchall()
        voices=c.execute('SELECT segment,name FROM voice_labels WHERE meeting_id=? AND base=?',(mid,base)).fetchall()
    for row in voices:
        if 0<=row['segment']<len(out['segments']):out['segments'][row['segment']]['speaker']=row['name']
    for row in rows:
        if 0<=row['segment']<len(out['segments']):
            out['segments'][row['segment']]['text']=row['text'];out['segments'][row['segment']]['edited_by_user']=True
    if rows:out['text']='\n'.join('[%02d:%02d] %s'%(int(s['start'])//60,int(s['start'])%60,s['text']) for s in out['segments'])
    out['has_edits']=bool(rows)
    return out

def status(root,mid,transcript):
    with db(root) as c:row=c.execute('SELECT signature,at FROM transcript_approval WHERE meeting_id=?',(mid,)).fetchone()
    return {'approved':bool(row and row['signature']==signature(transcript)),'approved_at':row['at'] if row and row['signature']==signature(transcript) else None}

def edit(root,mid,index,text,expected_signature):
    if not re.fullmatch(r'reuniao-[a-f0-9]{24}',mid):raise ValueError('Reunião inválida.')
    if type(index) is not int or not isinstance(text,str) or not 1<=len(text.strip())<=5000:raise ValueError('Trecho inválido.')
    with revision_lock(root,mid):
        raw=read(Path(root)/'reunioes/jobs'/mid/'transcript.json');base=signature(raw)
        shown=effective(root,mid,raw)
        if signature(shown)!=expected_signature:raise ValueError('A transcrição mudou. Atualize a reunião antes de salvar; sua edição não foi aplicada.')
        if not 0<=index<len(raw.get('segments',[])):raise ValueError('Trecho não encontrado.')
        current=shown['segments'][index]['text'];now=time.time()
        with db(root) as c:
            c.execute('INSERT OR REPLACE INTO transcript_edits VALUES(?,?,?,?,?)',(mid,base,index,text.strip(),now))
            c.execute('INSERT INTO transcript_edit_log(meeting_id,segment,before_text,after_text,at) VALUES(?,?,?,?,?)',(mid,index,current,text.strip(),now))
            c.execute('DELETE FROM transcript_approval WHERE meeting_id=?',(mid,))
    return {'state':'saved','analysis_stale':True}

def approve(root,mid,expected_signature):
    if not re.fullmatch(r'reuniao-[a-f0-9]{24}',mid):raise ValueError('Reunião inválida.')
    with revision_lock(root,mid):
        raw=read(Path(root)/'reunioes/jobs'/mid/'transcript.json')
        transcript=effective(root,mid,raw)
        if signature(transcript)!=expected_signature:raise ValueError('A transcrição mudou. Confira a nova versão antes de marcar como revisada.')
        with db(root) as c:c.execute('INSERT OR REPLACE INTO transcript_approval VALUES(?,?,?)',(mid,signature(transcript),time.time()))
    return {'state':'reviewed','signature':signature(transcript)}
