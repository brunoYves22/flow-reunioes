"""Checklist de aceitação humano, separado da inspeção técnica da gravação."""
import time
from pathlib import Path
from reunioes.core import read,save,detail
from reunioes.revisao import signature

def record(root,mid,checks,revision):
    item=detail(root,mid)
    required=('own_voice','remote_voice','image','automatic_start','automatic_stop')
    if not isinstance(checks,dict) or set(checks)!=set(required) or any(type(v) is not bool for v in checks.values()):raise ValueError('Preencha os cinco itens de validação.')
    if revision!=item['transcript_revision']:raise ValueError('A transcrição mudou; confira a nova versão.')
    value={'meeting_id':mid,'checks':checks,'passed':all(checks.values()),'at':time.time(),'kind':'user_confirmation','revision':revision}
    save(Path(root)/'reunioes/jobs'/mid/'validation.json',value);return value
