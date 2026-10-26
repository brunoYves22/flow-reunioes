"""Preserva quadros e lê texto visível localmente, sem inferir o que não está legível."""
import json,os,subprocess
from pathlib import Path
from reunioes.core import read,save,update

def extract(root,item,folder):
    result_path=folder/'visual.json'
    if result_path.exists():return read(result_path)
    cfg=read(Path(root)/'audio/config.json');src=Path(item['source'])
    if src.suffix.casefold() not in ('.mkv','.mp4','.webm'):return {'status':'sem_video','frames':[],'text':''}
    frames=folder/'frames';frames.mkdir(exist_ok=True)
    update(root,item['id'],'transcribing','Organizando evidências visuais (quadros a cada 30 segundos)')
    command=[cfg['ffmpeg'],'-hide_banner','-loglevel','error','-nostdin','-y','-i',str(src),'-an','-vf','fps=1/30,scale=1280:-2','-frames:v','480',str(frames/'%04d.jpg')]
    try:
        subprocess.run(command,capture_output=True,check=True,timeout=300,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        output=folder/'ocr-local.json'
        script=(Path(root)/'reunioes/visual_ocr.ps1').read_text(encoding='utf-8')
        command='& {\n'+script+'\n} -Folder $env:FLOW_OCR_FOLDER -Output $env:FLOW_OCR_OUTPUT'
        task=subprocess.run(['powershell.exe','-NoProfile','-Command',command],env=dict(os.environ,FLOW_OCR_FOLDER=str(frames),FLOW_OCR_OUTPUT=str(output)),capture_output=True,timeout=600,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if task.returncode or not output.exists():raise ValueError('OCR local indisponível')
        rows=read(output)
        if isinstance(rows,dict):rows=[rows]
        text='\n'.join('[Visual %02d:%02d] %s'%(r['at']//60,r['at']%60,r['text']) for r in rows if r.get('text'))
        result={'status':'sampled_ocr','interval_seconds':30,'frames':rows,'text':text,
                'limitation':'Texto extraído de quadros a cada 30s; não cobre transições rápidas, gestos, expressões ou tudo que foi exibido. Vídeo completo preservado.'}
    except (OSError,ValueError,subprocess.SubprocessError):
        result={'status':'video_preservado_ocr_indisponivel','frames':[], 'text':'', 'limitation':'Vídeo preservado. Leitura visual automática indisponível; confira a gravação.'}
    save(result_path,result);return result
