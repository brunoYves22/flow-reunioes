"""Referências humanas, sugestões ASR parciais e nomes fornecidos pelo usuário."""
import gc,hashlib,json,re,subprocess,sys,time
from pathlib import Path
from reunioes.core import db,read,save,config
from reunioes.revisao import signature,effective,revision_lock,edit

def init(root):
    with db(root) as c:
        c.execute('CREATE TABLE IF NOT EXISTS human_references(meeting_id TEXT,base TEXT,segment INTEGER,reference TEXT,original TEXT,at REAL,PRIMARY KEY(meeting_id,base,segment))')
        c.execute('CREATE TABLE IF NOT EXISTS voice_labels(meeting_id TEXT,base TEXT,segment INTEGER,name TEXT,at REAL,PRIMARY KEY(meeting_id,base,segment))')
        c.execute('CREATE TABLE IF NOT EXISTS excerpt_jobs(id TEXT PRIMARY KEY,meeting_id TEXT,segment INTEGER,revision TEXT,start REAL,end REAL,state TEXT,suggestion TEXT,reason TEXT,created REAL,updated REAL)')

def current(root,mid,index,revision):
    if not re.fullmatch(r'reuniao-[a-f0-9]{24}',mid):raise ValueError('Reunião inválida.')
    raw=read(Path(root)/'reunioes/jobs'/mid/'transcript.json')
    shown=effective(root,mid,raw)
    if signature(shown)!=revision:raise ValueError('A transcrição mudou. Atualize antes de continuar.')
    if type(index) is not int or not 0<=index<len(shown.get('segments',[])):raise ValueError('Trecho inválido.')
    return raw,shown

def word_errors(reference,hypothesis):
    a=re.findall(r'\w+',reference.casefold());b=re.findall(r'\w+',hypothesis.casefold())
    if not a:raise ValueError('A referência precisa conter palavras.')
    prev=[(j,0,0,j) for j in range(len(b)+1)]
    for i,x in enumerate(a,1):
        row=[(i,0,i,0)]
        for j,y in enumerate(b,1):
            if x==y:row.append(prev[j-1]);continue
            e,s,d,n=prev[j-1];sub=(e+1,s+1,d,n)
            e,s,d,n=prev[j];delete=(e+1,s,d+1,n)
            e,s,d,n=row[-1];insert=(e+1,s,d,n+1)
            row.append(min((sub,delete,insert),key=lambda z:z[0]))
        prev=row
    e,s,d,n=prev[-1]
    return {'errors':e,'substitutions':s,'deletions':d,'insertions':n,'reference_words':len(a),'wer':e/len(a)}

def reference(root,mid,index,text,revision):
    if not isinstance(text,str) or not 1<=len(text.strip())<=5000:raise ValueError('Referência inválida.')
    with revision_lock(root,mid):
        raw,_=current(root,mid,index,revision)
        word_errors(text,raw['segments'][index]['text'])
        with db(root) as c:c.execute('INSERT OR REPLACE INTO human_references VALUES(?,?,?,?,?,?)',(mid,signature(raw),index,text.strip(),raw['segments'][index]['text'],time.time()))
    return metrics(root,mid,raw)

def metrics(root,mid,raw):
    with db(root) as c:rows=c.execute('SELECT reference,original FROM human_references WHERE meeting_id=? AND base=?',(mid,signature(raw))).fetchall()
    totals={k:0 for k in ('errors','reference_words','substitutions','deletions','insertions')}
    for r in rows:
        counts=word_errors(r['reference'],r['original'])
        for k in totals:totals[k]+=counts[k]
    return {**totals,'segments':len(rows),'wer':totals['errors']/totals['reference_words'] if totals['reference_words'] else None,'whole_meeting':False,
            'label':'Erros de palavras nos trechos com referência humana; não estima a reunião inteira.'}

def name_voice(root,mid,index,name,revision):
    if not isinstance(name,str) or not 1<=len(name.strip())<=100:raise ValueError('Informe um nome de até 100 caracteres.')
    with revision_lock(root,mid):
        raw,_=current(root,mid,index,revision)
        with db(root) as c:
            c.execute('INSERT OR REPLACE INTO voice_labels VALUES(?,?,?,?,?)',(mid,signature(raw),index,name.strip(),time.time()))
            c.execute('DELETE FROM transcript_approval WHERE meeting_id=?',(mid,))
    return {'state':'saved'}

def vocabulary(root,terms=None):
    path=Path(root)/'reunioes/vocabulary.json'
    if terms is not None:
        if not isinstance(terms,list) or len(terms)>80 or any(not isinstance(s,str) or not 1<=len(s.strip())<=60 for s in terms):raise ValueError('Use até 80 termos de até 60 caracteres.')
        if sum(len(s) for s in terms)>1200:raise ValueError('Vocabulário acima de 1200 caracteres.')
        save(path,{'terms':list(dict.fromkeys(s.strip() for s in terms))})
    return read(path).get('terms',[]) if path.exists() else ['FLOW','Sopha','YouTrack','Maestri']

def request_excerpt(root,mid,index,revision):
    with revision_lock(root,mid):
        _,shown=current(root,mid,index,revision);s=shown['segments'][index]
        start=max(0,float(s['start']));end=float(s['end'])
        if not 0<end-start<=180:raise ValueError('Selecione um trecho de até três minutos.')
        vocab=vocabulary(root)
        jid=hashlib.sha256(json.dumps([mid,index,revision,vocab]).encode()).hexdigest()[:32]
        now=time.time()
        with db(root) as c:
            c.execute('INSERT OR IGNORE INTO excerpt_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?)',(jid,mid,index,revision,start,end,'queued',None,'',now,now))
            c.execute("UPDATE excerpt_jobs SET state='queued',reason='',updated=? WHERE id=? AND state='failed'",(now,jid))
            row=dict(c.execute('SELECT * FROM excerpt_jobs WHERE id=?',(jid,)).fetchone())
        return row

def selected_words(words,start,end):
    return ' '.join(w['word'].strip() for w in words if start<=(w['start']+w['end'])/2<end).strip()

def recognize_excerpt(root,source,start,end):
    cfg=read(Path(root)/'audio/config.json');meeting=config(root)
    sys.path.insert(0,cfg['dependencies'])
    import numpy as np
    from faster_whisper import WhisperModel
    from operacoes.portal import portal_lock
    offset=max(0,start-1)
    with portal_lock({'runtime':str(root)},'audio-cpu'):
        audio=subprocess.run([cfg['ffmpeg'],'-v','error','-nostdin','-ss',str(offset),'-i',str(source),'-t',str(end+1-offset),'-map','0:a:0','-vn','-ac','1','-ar','16000','-f','s16le','-'],capture_output=True,check=True,timeout=90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).stdout
        samples=np.frombuffer(audio,dtype=np.int16).astype(np.float32)/32768
        model=WhisperModel(meeting.get('asr_model',cfg['model']),device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
        segments,_=model.transcribe(samples,language='pt',beam_size=8,temperature=0,condition_on_previous_text=False,vad_filter=True,word_timestamps=True,hotwords=', '.join(vocabulary(root)))
        words=[{'start':offset+w.start,'end':offset+w.end,'word':w.word} for s in segments for w in (s.words or [])]
        result=selected_words(words,start,end)
        del model;gc.collect()
    if not result:raise ValueError('Nenhuma fala reconhecida neste trecho. Confira a gravação.')
    return result

def run_excerpt(root,jid):
    with db(root) as c:
        row=c.execute("SELECT * FROM excerpt_jobs WHERE id=? AND state='queued'",(jid,)).fetchone()
        if not row:return
        job=dict(row);source=c.execute('SELECT source FROM meetings WHERE id=?',(job['meeting_id'],)).fetchone()['source']
        c.execute("UPDATE excerpt_jobs SET state='running',updated=? WHERE id=?",(time.time(),jid))
    try:
        suggestion=recognize_excerpt(root,source,job['start'],job['end']);state='ready';reason=''
    except Exception as e:
        suggestion=None;state='queued' if isinstance(e,ValueError) and str(e).startswith('portal_busy') else 'failed'
        reason=str(e)[:200] if isinstance(e,ValueError) else 'Falha no reconhecimento local; original e correções preservados.'
    with db(root) as c:c.execute('UPDATE excerpt_jobs SET state=?,suggestion=?,reason=?,updated=? WHERE id=?',(state,suggestion,reason,time.time(),jid))

def accept_excerpt(root,jid,revision):
    with db(root) as c:job=c.execute('SELECT * FROM excerpt_jobs WHERE id=?',(jid,)).fetchone()
    if not job or job['state']!='ready':raise ValueError('Sugestão ainda não disponível.')
    if revision!=job['revision']:raise ValueError('A versão mudou desde a tentativa. Compare o texto e edite manualmente para preservar suas correções.')
    result=edit(root,job['meeting_id'],job['segment'],job['suggestion'],revision)
    with db(root) as c:c.execute("UPDATE excerpt_jobs SET state='accepted',updated=? WHERE id=?",(time.time(),jid))
    return result
