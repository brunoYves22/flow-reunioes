"""MP4 de consulta local, sem alterar o original; streaming com Range autenticado."""
import re,subprocess
from pathlib import Path
from reunioes.core import read

def preview_path(root,mid):
    if not re.fullmatch(r'reuniao-[a-f0-9]{24}',mid):raise ValueError('Reunião inválida.')
    return Path(root)/'reunioes/jobs'/mid/'player.mp4'

def prepare(root,item):
    import json
    target=preview_path(root,item['id'])
    if target.exists():return target
    src=Path(item['source'])
    if src.suffix=='.txt':raise ValueError('Transcrição importada sem gravação de áudio/vídeo.')
    target.parent.mkdir(exist_ok=True,parents=True);temp=target.with_name('player-building.mp4')
    cfg=read(Path(root)/'audio/config.json')
    # Evita áudio duplicado quando há múltiplas faixas do OBS (desktop/Brave + microfone)
    try:
        probe=subprocess.run([cfg['ffprobe'],'-v','error','-show_streams','-of','json',str(src)],capture_output=True,check=True,timeout=40,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        streams=json.loads(probe.stdout).get('streams',[])
        audio_streams=[s for s in streams if s.get('codec_type')=='audio']
    except Exception:
        audio_streams=[]
    if len(audio_streams)>=3:
        # Faixa 2: áudio digital limpo do Meet; Faixa 1: mic filtrado com noise gate para zerar eco/vazamento dos alto-falantes
        cmd=[cfg['ffmpeg'],'-hide_banner','-loglevel','error','-nostdin','-y','-i',str(src),
             '-map','0:v:0?',
             '-filter_complex','[0:a:2]volume=1.0[brave];[0:a:1]agate=threshold=0.04:range=0.01:attack=10:release=200[mic];[brave][mic]amix=inputs=2:duration=longest:dropout_transition=0[aout]',
             '-map','[aout]','-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',str(temp)]
    else:
        cmd=[cfg['ffmpeg'],'-hide_banner','-loglevel','error','-nostdin','-y','-i',str(src),'-map','0:v:0?','-map','0:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',str(temp)]
    subprocess.run(cmd,capture_output=True,check=True,timeout=600,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    temp.replace(target);return target

def byte_range(header,size):
    if not header:return 0,size-1,False
    match=re.fullmatch(r'bytes=(\d*)-(\d*)',header)
    if not match or not any(match.groups()):raise ValueError('Intervalo inválido.')
    a,b=match.groups()
    if not a:
        length=int(b)
        if length<=0:raise ValueError('Intervalo inválido.')
        return max(0,size-length),size-1,True
    start=int(a);end=min(size-1,int(b)) if b else size-1
    if start>=size or start>end:raise ValueError('Intervalo inválido.')
    return start,end,True
