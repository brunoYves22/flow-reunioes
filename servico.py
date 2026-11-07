"""Aplicação local de reuniões; agenda não usa sessões de IA pagas."""
import argparse, hmac, json, os, re, secrets, subprocess, sys, threading, time
from datetime import datetime,timedelta
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from reunioes.core import init,config,db,listing,detail,ingest,update,forward,save,note,read,delete_meeting
from reunioes.sentinela import MeetingSentinel,notify_user
from reunioes.meet_capture import MeetCapture

def serve(root):
    root=Path(root);init(root);cfg=config(root)
    token=secrets.token_urlsafe(32);wake=threading.Event();gate=threading.Lock()
    previews={};preview_gate=threading.Lock()
    def preview(mid):
        from reunioes.media import prepare
        with preview_gate:
            if previews.get(mid)=='building':return
            previews[mid]='building'
        try:prepare(root,detail(root,mid));previews[mid]='ready'
        except Exception:previews[mid]='failed'
    meet_cfg_path=root/'reunioes/meet-private.json'
    meet_cfg=json.loads(meet_cfg_path.read_text(encoding='utf-8')) if meet_cfg_path.exists() else {}
    def capture_saved(path):
        path=Path(path).resolve()
        if path.parent!=(root/'reunioes/entrada').resolve():raise ValueError('Arquivo fora da pasta de captura.')
        result=ingest(root,path,title='Meet — '+path.stem)
        save(root/'reunioes/last-capture.json',{'path':str(path),'meeting_id':result['id'],'saved_at':time.time()})
        wake.set()
    meet=MeetCapture(root,on_saved=capture_saved)
    state={'worker':'Disponível','last_cycle':None,'next_windows':cfg['hours'],'local_only':True,'schedule_error':'','model_ready':False,'sentinel':'iniciando_observacao','auto_record_enabled':cfg.get('auto_record',False) is True}
    storage_cache={'at':0,'value':None}
    def storage_status():
        if time.monotonic()-storage_cache['at']>30 or storage_cache['value'] is None:
            from reunioes.armazenamento import summary
            storage_cache.update(at=time.monotonic(),value=summary(root))
        return storage_cache['value']
    # Port binding happens before recovery: a second instance cannot mutate a live job.
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def valid(self,write=False):
            host=self.headers.get('Host','');expected='http://'+host
            return host in ('127.0.0.1:'+str(cfg['port']),'localhost:'+str(cfg['port'])) and self.headers.get('Origin',expected)==expected and (not write or (self.headers.get('Origin')==expected and hmac.compare_digest(self.headers.get('X-Meeting-Token',''),token)))
        def reply(self,status,data,html=False):
            raw=data if html else json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type','text/html; charset=utf-8' if html else 'application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','SAMEORIGIN')
            self.send_header('Referrer-Policy','no-referrer')
            if self.path=='/api/status':self.send_header('Set-Cookie','FLOW_MEDIA='+token+'; HttpOnly; SameSite=Strict; Path=/api/media')
            if self.path=='/api/meet' and meet_cfg.get('origin') and self.headers.get('Origin')==meet_cfg['origin']:
                self.send_header('Access-Control-Allow-Origin',meet_cfg['origin'])
            self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'")
            self.end_headers();self.wfile.write(raw)
        def do_OPTIONS(self):
            if self.path!='/api/meet' or not meet_cfg.get('origin') or self.headers.get('Origin')!=meet_cfg['origin']:
                return self.reply(403,{'error':'Origem inválida.'})
            self.send_response(204)
            self.send_header('Access-Control-Allow-Origin',meet_cfg['origin'])
            self.send_header('Access-Control-Allow-Methods','POST')
            self.send_header('Access-Control-Allow-Headers','Content-Type, X-Meet-Token')
            self.end_headers()
        def do_GET(self):
            if not self.valid():return self.reply(403,{'error':'Origem não autorizada.'})
            url=urlsplit(self.path)
            if url.path=='/':return self.reply(200,(root/'reunioes/painel.html').read_bytes(),True)
            if url.path=='/app.js':return self.reply_js(root/'reunioes/app.js')
            if url.path=='/api/status':
                from reunioes.precisao import vocabulary
                stark_hb = {'state': 'offline', 'status': 'offline'}
                try:
                    hb_f = root / 'operacoes/heartbeats/sentinela-whatsapp.json'
                    if hb_f.exists():
                        stark_hb = json.loads(hb_f.read_text(encoding='utf-8'))
                        stale = (time.time() - float(stark_hb.get('observed', 0))) > 35
                        raw_st = stark_hb.get('status') or stark_hb.get('state') or 'aguardando_portal'
                        stark_hb['state'] = 'offline' if stale else ('qr_pendente' if (stark_hb.get('qr_required') or raw_st == 'qr_pendente') else ('ativo' if raw_st in ('online', 'ativo') else 'aguardando_portal'))
                except Exception:
                    pass
                pending_props = 0
                try:
                    pf = root / 'operacoes/propostas_pendentes.json'
                    if pf.exists():
                        now_ts = time.time()
                        props_list = json.loads(pf.read_text(encoding='utf-8'))
                        if any(x.get('status') == 'aguardando_aprovacao' and x.get('created_at') and (now_ts - float(x['created_at'])) > 7 * 86400 for x in props_list):
                            for x in props_list:
                                if x.get('status') == 'aguardando_aprovacao' and x.get('created_at') and (now_ts - float(x['created_at'])) > 7 * 86400:
                                    x['status'] = 'expirada'
                            pf.write_text(json.dumps(props_list, ensure_ascii=False, indent=2), encoding='utf-8')
                        pending_props = sum(1 for x in props_list if x.get('status') == 'aguardando_aprovacao')
                except Exception:
                    pass
                return self.reply(200,{'token':token,'meetings':listing(root),'runtime':state,'inbox':str(root/'reunioes/entrada'),'memory':cfg['memory'],'model':cfg['model'],'asr_label':config(root).get('asr_label','Whisper base — modelo anterior'),'storage':storage_status(),'vocabulary':vocabulary(root),'ecosystem':{'stark_sentinel':stark_hb,'pending_proposals':pending_props}})
            if url.path=='/api/media':return self.stream_media(parse_qs(url.query).get('id',[''])[0])
            if url.path=='/api/detail':
                if not hmac.compare_digest(self.headers.get('X-Meeting-Token',''),token):return self.reply(403,{'error':'Atualize a página.'})
                try:
                    value=detail(root,parse_qs(url.query).get('id',[''])[0])
                    from reunioes.media import preview_path
                    value['preview_ready']=preview_path(root,value['id']).exists()
                    value['preview_status']=previews.get(value['id'],'not_started')
                    return self.reply(200,value)
                except ValueError as e:return self.reply(400,{'error':str(e)})
            self.reply(404,{'error':'Não encontrado.'})
        def reply_js(self,path):
            raw=path.read_bytes();self.send_response(200);self.send_header('Content-Type','application/javascript; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
        def stream_media(self,mid):
            from http.cookies import SimpleCookie
            from reunioes.media import preview_path,byte_range
            cookie=SimpleCookie(self.headers.get('Cookie',''))
            if 'FLOW_MEDIA' not in cookie or not hmac.compare_digest(cookie['FLOW_MEDIA'].value,token):return self.reply(403,{'error':'Abra o painel de reuniões para assistir.'})
            try:
                path=preview_path(root,mid)
                if not path.exists():return self.reply(409,{'error':'Prévia ainda em preparação.'})
                size=path.stat().st_size;start,end,partial=byte_range(self.headers.get('Range'),size)
            except ValueError:return self.reply(416,{'error':'Intervalo inválido.'})
            self.send_response(206 if partial else 200);self.send_header('Content-Type','video/mp4');self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1));self.send_header('Cache-Control','no-store');self.send_header('Cross-Origin-Resource-Policy','same-origin')
            if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            try:
                with path.open('rb') as f:
                    f.seek(start);left=end-start+1
                    while left:
                        chunk=f.read(min(left,262144))
                        if not chunk:break
                        self.wfile.write(chunk);left-=len(chunk)
            except (BrokenPipeError,ConnectionResetError):pass
        def do_POST(self):
            if self.path=='/api/meet':
                if not meet_cfg.get('token') or self.headers.get('Host')!='127.0.0.1:'+str(cfg['port']) or self.headers.get('Origin')!=meet_cfg.get('origin') or not hmac.compare_digest(self.headers.get('X-Meet-Token',''),meet_cfg['token']):
                    return self.reply(403,{'error':'Extensão não autorizada.'})
                try:
                    size=int(self.headers.get('Content-Length',0))
                    if not 0<size<=512 or self.headers.get('Content-Type')!='application/json':raise ValueError('Formato inválido.')
                    data=json.loads(self.rfile.read(size))
                    return self.reply(200,meet.signal(data['tab'],data['active'],data.get('window_ready',False)))
                except (ValueError,KeyError,TypeError):return self.reply(400,{'error':'Sinal inválido.'})
            if not self.valid(True):return self.reply(403,{'error':'Atualize a página; sessão/origem inválida.'})
            try:
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('Formato inválido.')
                size=int(self.headers.get('Content-Length',0))
                if not 0<size<=16000:raise ValueError('Pedido acima do limite.')
                data=json.loads(self.rfile.read(size))
                if self.path=='/api/import':result=ingest(root,data['path'],data.get('title',''),data.get('date',''))
                elif self.path=='/api/preview':
                    item=detail(root,data['id']);threading.Thread(target=preview,args=(item['id'],),daemon=True).start();result={'state':'preparing'}
                elif self.path=='/api/edit-segment':
                    item=detail(root,data['id'])
                    if item['state'] in ('queued','transcribing','extracting'):raise ValueError('Aguarde o processamento terminar para editar.')
                    from reunioes.revisao import edit
                    result=edit(root,item['id'],data['index'],data['text'],data.get('revision'));note(root,item['id'])
                elif self.path=='/api/approve-transcript':
                    item=detail(root,data['id'])
                    if not item['transcript'] or item['state'] not in ('ready','review_required'):raise ValueError('Aguarde a transcrição terminar.')
                    from reunioes.revisao import approve
                    result=approve(root,item['id'],data.get('revision'));note(root,item['id'])
                elif self.path=='/api/delete-meeting':
                    result=delete_meeting(root,data['id'])
                elif self.path=='/api/bruno-action-toggle':
                    item=detail(root,data['id'])
                    idx=int(data.get('index',-1))
                    done=bool(data.get('done',True))
                    folder=root/'reunioes/jobs'/item['id']
                    analysis_file=folder/'analysis.json'
                    if analysis_file.exists():
                        analysis=read(analysis_file)
                        bruno_items=analysis.get('direcionado_para_bruno',[])
                        target_item=None
                        if 0<=idx<len(bruno_items):
                            target_item=bruno_items[idx]
                        elif 'quote' in data:
                            for b in bruno_items:
                                if b.get('quote')==data['quote']:
                                    target_item=b;break
                        if target_item is not None:
                            target_item['done']=done
                            save(analysis_file,analysis)
                            try:note(root,item['id'])
                            except Exception:pass
                            result={'ok':True,'index':idx,'done':done}
                        else:raise ValueError('Item não encontrado.')
                    else:raise ValueError('Análise não encontrada.')
                elif self.path=='/api/dispatch-bruno-action':
                    item=detail(root,data['id'])
                    idx=int(data.get('index',-1))
                    folder=root/'reunioes/jobs'/item['id']
                    analysis_file=folder/'analysis.json'
                    if not analysis_file.exists():raise ValueError('Análise não encontrada.')
                    analysis=read(analysis_file)
                    bruno_items=analysis.get('direcionado_para_bruno') or analysis.get('tasks') or []
                    if not (0<=idx<len(bruno_items)):raise ValueError('Ação não encontrada.')
                    target_item=bruno_items[idx]
                    if target_item.get('central_task'):
                        result={'ok':True,'task_id':target_item['central_task'],'reused':True}
                    else:
                        from operacoes.entrada import submit
                        area=target_item.get('area') or target_item.get('owner') or 'Ação'
                        act_desc=target_item.get('action') or target_item.get('description') or ''
                        details_txt=target_item.get('details') or ''
                        quote_txt=target_item.get('quote') or ''
                        req_text=f'Ação de reunião ({item.get("title",item["id"])}) — [{area}] {act_desc}. {details_txt} Evidência: "{quote_txt}"'.strip()
                        req_key=re.sub(r'[^a-zA-Z0-9_-]','-',f"reuniao-{item['id'][-24:]}-b{idx+1}-{int(time.time())%100000}")[:78]
                        sub=submit(root,{'key':req_key,'request':req_text,'mode':'auto','acceptance':'Executar ou registrar andamento e confirmar evidência.'})
                        target_item['central_task']=sub['task_id']
                        save(analysis_file,analysis)
                        try:
                            pf=root/'operacoes/propostas_pendentes.json'
                            plist=json.loads(pf.read_text(encoding='utf-8')) if pf.exists() else []
                            prop_id=f"{item['id']}-bruno-{idx+1}"
                            if not any(x.get('id')==prop_id for x in plist):
                                plist.append({'id':prop_id,'meeting_id':item['id'],'meeting_title':item.get('title',item['id']),'index':idx+1,'area':area,'action':act_desc,'details':details_txt,'quote':quote_txt,'timestamp':target_item.get('timestamp',0),'status':'aguardando_aprovacao','created_at':time.time(),'central_task':sub['task_id']})
                                pf.write_text(json.dumps(plist,ensure_ascii=False,indent=2),encoding='utf-8')
                        except Exception:pass
                        result={'ok':True,'task_id':sub['task_id'],'reused':False}
                elif self.path in ('/api/reference','/api/name-voice','/api/retry-excerpt'):
                    item=detail(root,data['id'])
                    if item['state'] not in ('ready','review_required','failed'):raise ValueError('Aguarde o processamento terminar.')
                    from reunioes.precisao import reference,name_voice,request_excerpt
                    if self.path=='/api/reference':
                        if data.get('confirmed') is not True:raise ValueError('Confirme que ouviu e conferiu este trecho.')
                        result=reference(root,item['id'],data['index'],data['text'],data.get('revision'))
                    elif self.path=='/api/name-voice':result=name_voice(root,item['id'],data['index'],data['name'],data.get('revision'));note(root,item['id'])
                    else:result=request_excerpt(root,item['id'],data['index'],data.get('revision'));wake.set()
                elif self.path=='/api/accept-excerpt':
                    from reunioes.precisao import accept_excerpt
                    result=accept_excerpt(root,data['job_id'],data.get('revision'))
                    with db(root) as c:mid=c.execute('SELECT meeting_id FROM excerpt_jobs WHERE id=?',(data['job_id'],)).fetchone()[0]
                    note(root,mid)
                elif self.path=='/api/vocabulary':
                    from reunioes.precisao import vocabulary
                    result={'terms':vocabulary(root,data['terms'])}
                elif self.path=='/api/proposal-preview':
                    from reunioes.evidencias import proposal_preview
                    result=proposal_preview(root,data['id'],data['description'])
                elif self.path=='/api/storage-policy':
                    from reunioes.armazenamento import policy
                    result=policy(root,data['days']);storage_cache['at']=0
                elif self.path in ('/api/backup','/api/cleanup'):
                    if meet.owned or not gate.acquire(blocking=False):raise ValueError('Aguarde captura e processamento terminarem para fazer manutenção.')
                    try:
                        from reunioes.armazenamento import backup,cleanup
                        result=backup(root)
                        if self.path=='/api/cleanup':result=cleanup(root)
                        storage_cache['at']=0
                    finally:gate.release()
                elif self.path=='/api/validation':
                    from reunioes.validacao import record
                    result=record(root,data['id'],data['checks'],data.get('revision'))
                elif self.path in ('/api/reprocess','/api/rebuild-report'):
                    item=detail(root,data['id'])
                    if item['state'] in ('queued','transcribing','extracting'):raise ValueError('Já está na fila ou em processamento.')
                    if self.path=='/api/reprocess':save(root/'reunioes/jobs'/item['id']/'asr-control.json',{'revision':secrets.token_hex(12)})
                    save(root/'reunioes/jobs'/item['id']/'report-control.json',{'report_only':self.path=='/api/rebuild-report'})
                    update(root,item['id'],'queued','Nova versão solicitada; original preservado.');wake.set();result={'state':'queued'}
                elif self.path=='/api/process':wake.set();result={'state':'Fila acionada; execução serial local.'}
                elif self.path=='/api/retry':
                    item=detail(root,data['id'])
                    if item['state']!='failed':raise ValueError('Apenas falhas podem ser retomadas.')
                    update(root,item['id'],'queued','Retomada solicitada');wake.set();result={'state':'queued'}
                elif self.path=='/api/forward':result=forward(root,data['id'],data['description'],data['mode'])
                elif self.path=='/api/folder':
                    path=root/'reunioes/entrada' if data['kind']=='inbox' else Path(cfg['memory'])
                    path.mkdir(parents=True,exist_ok=True);os.startfile(str(path));result={'state':'Pasta aberta'}
                elif self.path=='/api/open-recording':
                    item=detail(root,data['id']);os.startfile(item['source']);result={'state':'Gravação original aberta no player.'}
                elif self.path=='/api/open-note':
                    item=detail(root,data['id']);os.startfile(item['note']);result={'state':'Relatório Markdown aberto.'}
                elif self.path=='/api/obs':
                    exe=Path(cfg['obs'])
                    if not exe.exists():raise ValueError('OBS ainda não instalado.')
                    subprocess.Popen([str(exe),'--profile','Maestri FLOW','--collection','Maestri FLOW'],cwd=exe.parent,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    result={'state':'OBS aberto. Confira os medidores e clique Iniciar gravação.'}
                else:return self.reply(404,{'error':'Não encontrado.'})
                self.reply(200,result)
            except (ValueError,KeyError,TypeError) as e:self.reply(400,{'error':str(e)[:300]})
            except Exception:self.reply(503,{'error':'Falha local; nenhum envio confirmado. Checkpoint preservado.'})

    server=ThreadingHTTPServer(('127.0.0.1',cfg['port']),Handler)
    from reunioes.recuperacao import recover_jobs
    recovered=recover_jobs(root)
    with db(root) as c:
        c.execute("UPDATE excerpt_jobs SET state='queued',reason='Retomando após reinício' WHERE state='running'")
    state['recovered_jobs']=recovered
    wake.set()

    def cycle():
        if not gate.acquire(blocking=False):return
        try:
            from reunioes.processar import process,api
            from reunioes.precisao import run_excerpt
            with db(root) as c:excerpt_jobs=[r['id'] for r in c.execute("SELECT id FROM excerpt_jobs WHERE state='queued' ORDER BY created")]
            for jid in excerpt_jobs:
                state['worker']='Conferindo trecho com reconhecimento local';run_excerpt(root,jid)
            # Só inventariar a pasta dedicada; jamais varrer Downloads/Documentos.
            for p in (root/'reunioes/entrada').iterdir():
                try:
                    # source_lock em ingest impede importar gravação ainda aberta no OBS.
                    if p.is_file() and p.stat().st_size>0:ingest(root,p)
                except (ValueError,OSError):pass
            with db(root) as c:
                queued=[dict(m) for m in c.execute("SELECT id FROM meetings WHERE state='queued' ORDER BY created")]
            if not queued:return
            agy_bin = Path(r'~\AppData\Local\agy\bin\agy_real.exe')
            if not agy_bin.exists():
                state['worker']='Preparando modelo local'
                ollama=Path(cfg['ollama'])
                try:api('/api/tags',timeout=5)
                except Exception:
                    env=dict(os.environ,OLLAMA_NO_CLOUD='1',OLLAMA_HOST='127.0.0.1:11434',OLLAMA_MAX_LOADED_MODELS='1',OLLAMA_NUM_PARALLEL='1')
                    subprocess.Popen([str(ollama),'serve'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    for _ in range(30):
                        try:api('/api/tags',timeout=2);break
                        except Exception:time.sleep(1)
                available=api('/api/tags',timeout=10)
                if cfg['model'] not in [m['name'] for m in available.get('models',[])]:raise ValueError('Modelo local não instalado. Concluir download pelo Ollama.')
            for item in queued:
                mid=item['id'];state['worker']='Processando '+mid
                process(root,mid)
                # Notificar o usuário após processamento bem-sucedido
                try:
                    with db(root) as c:
                        row=c.execute("SELECT state,title FROM meetings WHERE id=?", (mid,)).fetchone()
                    if row and row['state'] in ('ready','review_required'):
                        d=detail(root,mid)
                        ext=d.get('analysis') or {}
                        n_tasks=len(ext.get('tasks',[]))
                        n_decisions=len(ext.get('decisions',[]))
                        n_bruno=len(ext.get('direcionado_para_bruno',[]))
                        summary_txt=ext.get('summary','')
                        title=row['title'] or mid[:16]
                        body=f"{summary_txt[:120]}..." if len(summary_txt)>120 else summary_txt
                        if n_bruno:
                            body=f"🎯 {n_bruno} prioridade(s) para Bruno!\n" + body
                        elif n_tasks or n_decisions:
                            body+=f"\n{n_tasks} tarefa(s), {n_decisions} decisão(ões)"
                        if row['state']=='review_required':body='Baixa confiança no áudio. Revise a gravação antes de usar os resultados.'
                        notify_user(('Revisão necessária — ' if row['state']=='review_required' else 'Reunião processada — ')+title, body or 'Processamento concluído.')
                except Exception:
                    pass
            from reunioes.armazenamento import backup
            backup(root);storage_cache['at']=0
        except Exception as e:state['schedule_error']=str(e)[:200] if isinstance(e,ValueError) else type(e).__name__
        finally:state['last_cycle']=time.time();state['worker']='Disponível';gate.release()

    # --- Sentinela de reuniões (thread dedicada) ---
    sentinel=meet if cfg.get('capture_mode')=='meet_brave' else MeetingSentinel(root, on_meeting_ended=lambda: wake.set())

    def sentinel_loop():
        previous=None
        while True:
            try:
                sentinel.tick(3)
                state['sentinel']=sentinel.status
                state['sentinel_reason']=sentinel.reason
                if isinstance(sentinel,MeetCapture):
                    state['capture_owned']=sentinel.owned
                    state['last_capture']=sentinel.last_capture
                    state['capture_recovery_warning']=sentinel.recovery_warning
                    state['meet_presence']=sentinel.presence_status()
                    state['audio_levels']=sentinel.obs.audio_health.snapshot(time.monotonic(),sentinel.owned)
                state['auto_record_enabled']=config(root).get('auto_record',False) is True
                current=(state['sentinel'],state['sentinel_reason'])
                if current!=previous:
                    event={'at':time.time(),'state':current[0],'reason':current[1],
                           'capture_owned':state.get('capture_owned',False)}
                    with (root/'reunioes/capture-events.jsonl').open('a',encoding='utf-8') as log:
                        log.write(json.dumps(event,ensure_ascii=False)+'\n')
                    previous=current
            except Exception as e:
                state['sentinel']='erro';state['sentinel_reason']=type(e).__name__
            time.sleep(3)
    threading.Thread(target=sentinel_loop, daemon=True, name='sentinela').start()

    def loop():
        while True:
            try:
                now=datetime.now();ledger=root/'reunioes/schedule.json'
                old=json.loads(ledger.read_text()) if ledger.exists() else {}
                from reunioes.processar import api
                try:state['model_ready']=cfg['model'] in [m['name'] for m in api('/api/tags',timeout=2).get('models',[])]
                except Exception:state['model_ready']=False
                due=[(now.date()-timedelta(days=1)).isoformat()+'T'+max(cfg['hours'])]
                due += [now.date().isoformat()+'T'+h for h in cfg['hours'] if h<=now.strftime('%H:%M')]
                window=max(due) if due else None
                scheduled=bool(window and window>old.get('window',''))
                manual=wake.is_set()
                # Recupera arquivos fechados e tarefas parciais mesmo fora das janelas de agenda.
                from reunioes.recuperacao import scan_closed
                if scan_closed(root):manual=True
                with db(root) as c:
                    if c.execute("SELECT 1 FROM meetings WHERE state='queued' UNION ALL SELECT 1 FROM excerpt_jobs WHERE state='queued' LIMIT 1").fetchone():manual=True
                if manual:wake.clear()
                if manual or scheduled:
                    state['schedule_error']='';cycle()
                    if scheduled and not state['schedule_error']:save(ledger,{'window':window,'at':time.time()})
                # Backup diário local; nunca inicia durante captura ou processamento.
                last=root/'reunioes/last-backup.json'
                age=time.time()-json.loads(last.read_text(encoding='utf-8')).get('at',0) if last.exists() else 999999
                if age>86400 and not meet.owned and gate.acquire(blocking=False):
                    try:
                        from reunioes.armazenamento import backup,cleanup
                        backup(root);cleanup(root);storage_cache['at']=0
                    finally:gate.release()
                save(root/'reunioes/heartbeat.json',{'observed':time.time(),**state})
            except Exception as e:state['schedule_error']=type(e).__name__
            wake.wait(30 if not state['schedule_error'] else 120)
    threading.Thread(target=loop,daemon=True).start();server.serve_forever()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--runtime',required=True);serve(Path(p.parse_args().runtime))
