"""Inspeção do contêiner: existência de faixas não comprova vozes inteligíveis."""
import json,subprocess
from pathlib import Path
from reunioes.core import read,save

def describe(metadata):
    streams=metadata.get('streams',[]);audio=[s for s in streams if s.get('codec_type')=='audio'];video=[s for s in streams if s.get('codec_type')=='video']
    return {'audio_tracks':len(audio),'has_video':bool(video),'duration':float(metadata.get('format',{}).get('duration',0)),
            'tracks':[{'number':i+1,'codec':s.get('codec_name'),'channels':s.get('channels'),'title':s.get('tags',{}).get('title','Faixa '+str(i+1))} for i,s in enumerate(audio)],
            'video':{'width':video[0].get('width'),'height':video[0].get('height')} if video else None,
            'human_validated':False,'limitation':'Faixas e imagem presentes no arquivo não comprovam vozes audíveis nem conteúdo legível. Confira no player.'}

def inspect(root,item):
    path=Path(root)/'reunioes/jobs'/item['id']/'media-info.json'
    if path.exists():return read(path)
    if Path(item['source']).suffix.lower()=='.txt':return None
    cfg=read(Path(root)/'audio/config.json')
    result=subprocess.run([cfg['ffprobe'],'-v','error','-show_format','-show_streams','-of','json',item['source']],capture_output=True,check=True,timeout=40,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    info=describe(json.loads(result.stdout));save(path,info);return info
