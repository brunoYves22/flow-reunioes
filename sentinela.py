"""Detecção local de chamadas. Nunca encerra OBS ou gravações manuais."""
import json, subprocess, time, winreg
from pathlib import Path
HIDDEN=getattr(subprocess,'CREATE_NO_WINDOW',0)

def notify_user(title,message):
    title=str(title)[:100].replace("'","''");message=str(message)[:240].replace("'","''")
    script="""Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Information
$n.BalloonTipTitle = '%s'
$n.BalloonTipText = '%s'
$n.Visible = $true
$n.ShowBalloonTip(4000)
Start-Sleep -Seconds 4
$n.Dispose()"""%(title,message)
    try:subprocess.run(['powershell.exe','-NoProfile','-Command',script],capture_output=True,timeout=8,creationflags=HIDDEN)
    except (OSError,subprocess.SubprocessError):pass

def check_active_mic():
    active=[]
    base=r'Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone'
    for path in (base+r'\NonPackaged',base):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,path) as key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    sub=winreg.EnumKey(key,i)
                    if sub=='NonPackaged':continue
                    try:
                        with winreg.OpenKey(key,sub) as entry:
                            start=winreg.QueryValueEx(entry,'LastUsedTimeStart')[0];stop=winreg.QueryValueEx(entry,'LastUsedTimeStop')[0]
                        name=sub.split('#')[-1]
                        if stop==0 and start>0 and name.casefold()!='obs64.exe':active.append(name)
                    except OSError:continue
        except OSError:continue
    return sorted(set(active))

def is_obs_running():
    try:
        out=subprocess.run(['tasklist','/FI','IMAGENAME eq obs64.exe','/NH'],capture_output=True,timeout=5,creationflags=HIDDEN)
        return out.returncode!=0 or b'obs64.exe' in out.stdout.lower()
    except (OSError,subprocess.SubprocessError):return True

class MeetingSentinel:
    def __init__(self,root,on_meeting_ended=None):
        self.root=Path(root);self.on_meeting_ended=on_meeting_ended
        self.is_recording=False;self.active_counter=0;self.silence_counter=0
        self.process=None;self.started_at=0;self.current_app='';self.notice_sent=False
        self.observed_file=None;self.status='desligado';self.reason=''
        self.launch_attempted=False

    def _own_file(self):
        if not self.started_at:return None
        entries=[p for p in (self.root/'reunioes/entrada').glob('*')
                 if p.is_file() and p.stat().st_mtime>=self.started_at-2 and p.suffix.casefold() in ('.mkv','.mp4')]
        return min(entries,key=lambda p:p.stat().st_mtime) if entries else None

    def tick(self,interval=3):
        cfg=json.loads((self.root/'reunioes/config.json').read_text(encoding='utf-8-sig'))
        enabled=cfg.get('auto_record',False) is True
        active=check_active_mic() if enabled or self.process else []
        self.reason=''
        if self.process is not None:
            from reunioes.core import source_lock
            candidate=self.observed_file or self._own_file()
            if candidate and candidate.exists():
                self.observed_file=candidate
                try:
                    with source_lock(candidate):closed=candidate.stat().st_size>0
                except ValueError:closed=False
                if closed:
                    self.is_recording=False;self.status='captura_salva';self.process=None;self.started_at=0
                    self.notice_sent=False;self.active_counter=0;self.silence_counter=0;self.observed_file=None
                    if self.on_meeting_ended:self.on_meeting_ended()
                    return
                self.is_recording=True
            elif self.process.poll() is not None:
                self.process=None;self.started_at=0;self.is_recording=False
                self.status='iniciar_manualmente';self.reason='OBS encerrou antes de confirmar arquivo gravado.';return
            if active:
                self.silence_counter=0;self.notice_sent=False;self.status='gravando' if self.is_recording else 'iniciando'
            else:
                self.silence_counter+=interval;self.status='aguardando_parada_manual'
                if self.silence_counter>=35 and not self.notice_sent:
                    self.notice_sent=True
                    notify_user('FLOW — chamada encerrada','Finalize a gravação pelo botão Parar gravação no OBS. O arquivo será processado após ser salvo.')
            return
        if not enabled:self.active_counter=0;self.status='desligado';return
        if active:
            self.current_app=active[0];self.active_counter+=interval
            if self.active_counter<6:self.status='detectando_chamada';return
            if is_obs_running():
                self.status='obs_em_uso';self.reason='OBS já aberto: gravação permanece sob controle manual.';return
            if self.launch_attempted:
                self.status='iniciar_manualmente';self.reason='Já houve solicitação nesta chamada; confira o OBS antes de tentar novamente.';return
            exe=Path(cfg.get('obs',''))
            if not exe.is_file():self.status='indisponivel';self.reason='Executável do OBS não encontrado.';return
            self.started_at=time.time();self.observed_file=None;self.notice_sent=False
            self.process=subprocess.Popen([str(exe),'--profile','Maestri FLOW','--collection','Maestri FLOW','--startrecording','--minimize-to-tray'],cwd=exe.parent,creationflags=HIDDEN)
            self.launch_attempted=True
            self.status='iniciando'
            notify_user('FLOW — chamada detectada','Início de gravação solicitado ao OBS. Confira o indicador; finalize pelo próprio OBS ao terminar.')
        else:self.active_counter=0;self.launch_attempted=False;self.status='ativo'
