"""Sinais mínimos do Meet e controle de capturas OBS iniciadas nesta instância."""
import base64
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path


class Obs:
    def __init__(self, root):
        self.root = Path(root)
        self.ws=None;self.interrupted=False;self.finished_paths=[]
        from reunioes.captura_saude import AudioHealth
        self.audio_health=AudioHealth()

    def connection_config(self):
        settings=json.loads((self.root/'reunioes/config.json').read_text(encoding='utf-8-sig'))
        # Store/MSIX can redirect APPDATA to a different OBS configuration.
        # Installation pins the authenticated config of the native OBS instance.
        path=Path(settings['obs_websocket_config']) if settings.get('obs_websocket_config') else Path(os.environ['APPDATA'])/'obs-studio/plugin_config/obs-websocket/config.json'
        return json.loads(path.read_text(encoding='utf-8-sig'))

    def call(self, kind, data=None):
        sys.path.insert(0, str(self.root / 'reunioes/deps')) if str(self.root / 'reunioes/deps') not in sys.path else None
        import websocket
        cfg = self.connection_config()
        if not cfg.get('server_enabled') or not cfg.get('auth_required'):
            raise ValueError('Ative o WebSocket autenticado do OBS.')
        ws = self.ws or websocket.create_connection('ws://127.0.0.1:' + str(cfg['server_port']), timeout=4, suppress_origin=True, http_no_proxy=['127.0.0.1'])
        try:
            if self.ws is None:
                hello = json.loads(ws.recv())
                auth = hello['d'].get('authentication')
                if not auth: raise ValueError('OBS sem autenticação.')
                secret = base64.b64encode(hashlib.sha256((cfg['server_password'] + auth['salt']).encode()).digest()).decode()
                proof = base64.b64encode(hashlib.sha256((secret + auth['challenge']).encode()).digest()).decode()
                ws.send(json.dumps({'op':1,'d':{'rpcVersion':1,'authentication':proof,'eventSubscriptions':64|65536}}))
                identified=ws.recv()
                if not identified or json.loads(identified).get('op') != 2:
                    raise ValueError('OBS recusou a autenticação. Confira a configuração nativa do OBS e a conexão do FLOW.')
                self.ws=ws
            rid = uuid.uuid4().hex
            ws.send(json.dumps({'op':6,'d':{'requestType':kind,'requestId':rid,'requestData':data or {}}}))
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                response = json.loads(ws.recv())
                if response.get('op')!=5:break
                event=response.get('d',{})
                if event.get('eventType')=='InputVolumeMeters':
                    for sample in event.get('eventData',{}).get('inputs',[]):
                        self.audio_health.observe(sample.get('inputName'),sample.get('inputLevelsMul',[]),time.monotonic())
                if event.get('eventType')=='RecordStateChanged' and event.get('eventData',{}).get('outputState') in ('OBS_WEBSOCKET_OUTPUT_STOPPING','OBS_WEBSOCKET_OUTPUT_STOPPED'):
                    self.interrupted=True
                    path=event.get('eventData',{}).get('outputPath')
                    if path:self.finished_paths.append(Path(path))
            item = response.get('d',{})
            if response.get('op') != 7 or item.get('requestId') != rid or not item.get('requestStatus',{}).get('result'):
                raise ValueError('OBS não confirmou ' + kind)
            return item.get('responseData',{})
        except Exception:
            ws.close();self.ws=None;self.interrupted=True
            raise


class MeetCapture:
    def __init__(self, root, on_saved=None, clock=time.monotonic, obs=None):
        self.root=Path(root); self.clock=clock; self.obs=obs or Obs(root); self.on_saved=on_saved
        self.lock=threading.Lock(); self.tabs={}; self.status='ativo'; self.reason=''
        self.owned=False; self.started=None; self.last_duration=0; self.until=None
        self.entered=None; self.launch_at=None; self.suppressed=False; self.last_status=None; self.checked_at=None
        self.owner_tab=None;self.start_pending=None;self.pending_files=[];self.last_capture=None
        self.probed_at=None;self.idle_status='iniciando_observacao';self.idle_reason='';self.last_signal_at=None
        journal=self.root/'reunioes/capture-session.json'
        self.recovery_warning=''
        if journal.exists():
            try:
                previous=json.loads(journal.read_text(encoding='utf-8'))
                if previous.get('state') in ('starting','recording'):
                    self.recovery_warning='Serviço reiniciou durante captura. Se o OBS ainda grava, finalize pelo OBS. O arquivo fechado será recuperado automaticamente.'
            except (ValueError,OSError):self.recovery_warning='Diário de captura ilegível; confira o OBS.'
        ledger=self.root/'reunioes/capture-pending.json'
        if ledger.exists():
            self.pending_files=[Path(p) for p in json.loads(ledger.read_text(encoding='utf-8')) if Path(p).parent.resolve()==(self.root/'reunioes/entrada').resolve()]

    def signal(self, tab, active, window_ready=False):
        if not isinstance(tab,str) or not tab.isdecimal() or len(tab)>20 or type(active) is not bool or type(window_ready) is not bool:
            raise ValueError('Sinal inválido.')
        with self.lock:
            self.tabs[tab]=(self.clock(),active,window_ready)
            self.last_signal_at=self.clock()
        return {'status':self.status}

    def presence_status(self):
        with self.lock:
            now=self.clock()
            return {'last_signal_age_seconds':round(max(0,now-self.last_signal_at)) if self.last_signal_at is not None else None,
                    'active_tabs':sum(v[1] and now-v[0]<30 for v in self.tabs.values())}

    def probe_idle(self,now):
        if self.probed_at is not None and now-self.probed_at<30:
            self.status,self.reason=self.idle_status,self.idle_reason;return
        self.probed_at=now
        try:
            rec=self.obs.call('GetRecordStatus')
            if rec.get('outputActive'):
                self.idle_status='obs_em_uso';self.idle_reason='OBS grava manualmente; o FLOW não controla esta captura.'
            elif self.obs.call('GetProfileList').get('currentProfileName')!='Maestri FLOW' or self.obs.call('GetSceneCollectionList').get('currentSceneCollectionName')!='Maestri FLOW':
                self.idle_status='indisponivel';self.idle_reason='Selecione perfil e coleção Maestri FLOW no OBS.'
            else:self.idle_status='ativo';self.idle_reason=''
        except Exception:
            self.idle_status='indisponivel';self.idle_reason='OBS sem conexão autenticada. A gravação automática ainda não está pronta; confira o controle WebSocket do OBS.'
        self.status,self.reason=self.idle_status,self.idle_reason

    def tick(self, interval=3):
        now=self.clock()
        with self.lock:
            self.tabs={k:v for k,v in self.tabs.items() if now-v[0]<180}
            candidates=[k for k,v in self.tabs.items() if v[1] and now-v[0]<30]
            target=self.owner_tab or (candidates[0] if candidates else None)
            presence=self.tabs.get(target)
            active=bool(presence and presence[1] and now-presence[0]<30)
            explicit_exit=bool(presence and not presence[1])
            last_active=presence[0] if presence else now-120
        cfg=json.loads((self.root/'reunioes/config.json').read_text(encoding='utf-8-sig'))
        # A saved event remains pending until the actual file is closed and ingested.
        if self.pending_files:
            path=self.pending_files[0]
            try:
                if self.on_saved:self.on_saved(path)
                self.pending_files.pop(0);self.last_capture=str(path)
                self._save_pending()
                self.status='captura_salva'
            except ValueError as e:
                if str(e).startswith('Arquivo em gravação'):
                    self.status='finalizando';self.reason='Aguardando arquivo fechado para iniciar processamento.'
                else:
                    self.pending_files.pop(0);self.status='erro';self.reason=str(e)[:180]
                    self._save_pending()
                    from reunioes.core import save
                    save(self.root/'reunioes/capture-ingest-error.json',{'path':str(path),'error':self.reason,'at':time.time()})
            except OSError:
                self.status='finalizando';self.reason='Aguardando arquivo fechado para iniciar processamento.'
        if not cfg.get('auto_record',False): active=False
        if active: self.until=None
        elif self.until is None:
            # Explicit departure: 60s. Missing heartbeat: at least 120s from last signal.
            self.until=now+cfg.get('meet_exit_grace',5) if explicit_exit else max(now,last_active+120)
        if not active and not self.owned and self.start_pending is None:
            self.entered=None
            if now >= self.until: self.suppressed=False; self.launch_at=None;self.owner_tab=None
            if not self.pending_files:
                if not cfg.get('auto_record',False):self.status='desligado';self.reason='Gravação automática desativada.'
                else:self.probe_idle(now)
            return
        if self.suppressed and not self.owned:
            self.status='obs_em_uso'; return
        if not self.owned and self.start_pending is None:
            if active and cfg.get('meet_video',False) and not presence[2]:
                self.status='atualize_extensao';self.reason='Recarregue FLOW Reuniões Meet no Brave e a aba do Meet.';return
            if self.entered is None: self.entered=now
            if now-self.entered<5: self.status='detectando_chamada'; return
        try:
            rec=self.obs.call('GetRecordStatus')
        except Exception:
            if self.owned:
                self.owned=False; self.suppressed=True
                self.status='erro'; self.reason='Conexão com OBS perdida; finalize a gravação manualmente.'; return
            if self.launch_at is None:
                # Never launch another OBS when one already exists.
                from reunioes.sentinela import is_obs_running
                if is_obs_running():
                    self.status='erro'; self.reason='OBS aberto sem conexão WebSocket. Confira a configuração.'; return
                exe=Path(cfg.get('obs',''))
                if not exe.is_file(): self.status='erro'; self.reason='OBS não encontrado.'; return
                subprocess.Popen([str(exe),'--profile','Maestri FLOW','--collection','Maestri FLOW','--minimize-to-tray'],cwd=exe.parent,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                self.launch_at=now
            self.status='iniciando' if now-self.launch_at<30 else 'erro'
            self.reason='Aguardando conexão autenticada com OBS.'; return
        self.reason=''
        if self.owned:
            if not rec.get('outputActive'):
                self.owned=False; self.suppressed=True; self.status='captura_salva'
                self._discover_saved()
                return
            if getattr(self.obs,'interrupted',False):
                self.owned=False; self.suppressed=True; self.status='obs_em_uso'
                self._discover_saved()
                self.reason='OBS sinalizou parada/reinício; gravação atual sob controle manual.'; return
            if not active and now>=self.until:
                try:
                    stopped=self.obs.call('StopRecord')
                except Exception:
                    # Uncertain stop must not be retried against a replacement recording.
                    self.owned=False; self.suppressed=True; self.status='erro'
                    self._discover_saved()
                    self.reason='Parada sem confirmação; confira OBS manualmente.'; return
                self.owned=False; self.suppressed=True; self.status='captura_salva'
                path=stopped.get('outputPath')
                if path:self._queue_saved(Path(path))
                else:self._discover_saved()
                return
            self.status='gravando' if active else 'aguardando_saida'; return
        if rec.get('outputActive'):
            if self.start_pending is not None and not getattr(self.obs,'interrupted',False):
                self.owned=True;self.owner_tab=target;self.start_pending=None;self.status='gravando';return
            self.start_pending=None;self.suppressed=True; self.status='obs_em_uso'; return
        try:
            if self.obs.call('GetProfileList').get('currentProfileName')!='Maestri FLOW' or self.obs.call('GetSceneCollectionList').get('currentSceneCollectionName')!='Maestri FLOW':
                self.status='erro'; self.reason='Selecione perfil e coleção Maestri FLOW no OBS.'; return
            if self.start_pending is not None:
                if now-self.start_pending<20:self.status='iniciando';return
                self.start_pending=None;self.suppressed=True;self.status='erro';self.reason='OBS não confirmou início em 20 segundos.';return
            if cfg.get('meet_video',False):
                from reunioes.meet_video import prepare
                prepare(self.obs,target)
            self.obs.interrupted=False
            self.obs.finished_paths=[]
            self.started=time.time()
            self.owner_tab=target
            self.start_pending=now
            self._journal('starting')
            self.obs.call('StartRecord')
            confirmed=self.obs.call('GetRecordStatus')
            # StartRecord is acknowledged before the encoder is necessarily active.
            for _ in range(4):
                if confirmed.get('outputActive') or getattr(self.obs,'interrupted',False):break
                time.sleep(0.5)
                confirmed=self.obs.call('GetRecordStatus')
            if not confirmed.get('outputActive'):
                self.status='iniciando';return
            if getattr(self.obs,'interrupted',False):raise ValueError('Gravação foi interrompida durante início.')
            self.owned=True; self.owner_tab=target;self.start_pending=None;self.status='gravando'
            self._journal('recording')
        except ValueError as e:
            if self.start_pending is None:
                self.status='atualizando_janela';self.reason=str(e)[:180];return
            self.suppressed=True; self.start_pending=None;self.status='erro'; self.reason='Início não confirmado; confira OBS antes de tentar outra gravação.'
        except Exception:
            self.suppressed=True; self.start_pending=None;self.status='erro'; self.reason='Início não confirmado; confira OBS antes de tentar outra gravação.'

    def _discover_saved(self):
        if self.started is None:return
        event_paths=getattr(self.obs,'finished_paths',[])
        if event_paths:
            for p in event_paths:
                if p.parent.resolve()==(self.root/'reunioes/entrada').resolve():self._queue_saved(p)
            self.obs.finished_paths=[]
            return
        files=[p for p in (self.root/'reunioes/entrada').glob('*.mkv') if p.stat().st_mtime>=self.started-2]
        for path in sorted(files,key=lambda p:p.stat().st_mtime):self._queue_saved(path)

    def _queue_saved(self,path):
        if path.parent.resolve()!=(self.root/'reunioes/entrada').resolve():return
        if path not in self.pending_files:self.pending_files.append(path)
        self._save_pending()
        self._journal('saved',str(path))

    def _journal(self,state,path=None):
        from reunioes.core import save
        save(self.root/'reunioes/capture-session.json',{'state':state,'tab':self.owner_tab,'started':self.started,'path':path,'updated':time.time()})

    def _save_pending(self):
        from reunioes.core import save
        save(self.root/'reunioes/capture-pending.json',[str(p) for p in self.pending_files])
