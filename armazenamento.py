"""Backups verificáveis e limpeza exclusivamente de derivados reproduzíveis."""
import contextlib,hashlib,json,shutil,sqlite3,time,threading
from pathlib import Path
from reunioes.core import db,read,save
_lock=threading.RLock()

def policy(root,days=None):
    path=Path(root)/'reunioes/storage-policy.json'
    if days is not None:
        if type(days) is not int or days not in (0,30,90):raise ValueError('Selecione preservar tudo, 30 ou 90 dias.')
        save(path,{'derivatives_days':days,'delete_originals':False,'require_review':True,'require_backup':True})
    return read(path) if path.exists() else {'derivatives_days':0,'delete_originals':False,'require_review':True,'require_backup':True}

def summary(root):
    root=Path(root);disk=shutil.disk_usage(root)
    usage={}
    for key,folder in [('originals',root/'reunioes/media'),('inbox',root/'reunioes/entrada'),('jobs',root/'reunioes/jobs')]:
        usage[key]=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file())
    last=root/'reunioes/last-backup.json'
    return {'free_bytes':disk.free,'total_bytes':disk.total,'usage':usage,'low_space':disk.free<5*1024**3,
            'policy':policy(root),'backup':read(last) if last.exists() else None,
            'backup_scope':'Banco, transcrições, relatórios, revisões e memória. Vídeos originais continuam no mesmo disco; cópia externa não configurada.'}

def backup(root):
    from reunioes.revisao import revision_lock
    with _lock,contextlib.ExitStack() as stack:
        with db(root) as c:ids=[r['id'] for r in c.execute('SELECT id FROM meetings ORDER BY id')]
        for mid in ids:stack.enter_context(revision_lock(root,mid))
        return _backup_locked(root)

def _backup_locked(root):
    root=Path(root)
    with _lock:
        target=root/'backups'/('reunioes-auto-'+time.strftime('%Y%m%d-%H%M%S')+'-'+str(time.time_ns())[-6:]);target.mkdir(parents=True)
        with contextlib.closing(sqlite3.connect(root/'reunioes/estado.sqlite')) as src,contextlib.closing(sqlite3.connect(target/'estado.sqlite')) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup do banco não passou na verificação.')
        files=[p for p in (root/'reunioes/jobs').rglob('*.json') if p.is_file()]
        from reunioes.core import config
        memory=Path(config(root)['memory']);files+=list(memory.rglob('*.md'))
        mapping=[{'path':'estado.sqlite','sha256':hashlib.sha256((target/'estado.sqlite').read_bytes()).hexdigest()}]
        for source in files:
            try:rel=source.relative_to(root/'reunioes');dest=target/'reunioes'/rel
            except ValueError:dest=target/'memory'/source.relative_to(memory)
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
            mapping.append({'path':str(dest.relative_to(target)),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
        save(target/'manifest.json',mapping)
        result={'path':str(target),'at':time.time(),'verified':True,'files':len(mapping),'media_included':False}
        save(root/'reunioes/last-backup.json',result);return result

def cleanup(root,now=None):
    root=Path(root);now=time.time() if now is None else now;days=policy(root)['derivatives_days'];freed=0;count=0
    if not days:return {'freed_bytes':0,'files':0}
    last=root/'reunioes/last-backup.json'
    if not last.exists():return {'freed_bytes':0,'files':0}
    b=read(last);target=Path(b.get('path',''))
    if not b.get('verified') or not (target/'manifest.json').is_file():return {'freed_bytes':0,'files':0}
    if not any(entry.get('path')=='estado.sqlite' for entry in read(target/'manifest.json')):raise ValueError('Backup antigo sem verificação do banco. Faça um novo backup antes da limpeza.')
    # Verificar os bytes de backup antes de qualquer remoção de derivados.
    for entry in read(target/'manifest.json'):
        path=target/entry['path']
        if not path.resolve().is_relative_to(target.resolve()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('Backup alterado; limpeza cancelada.')
    with contextlib.closing(sqlite3.connect('file:'+str(target/'estado.sqlite')+'?mode=ro',uri=True)) as c:
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup do banco inválido; limpeza cancelada.')
    with db(root) as c:rows=c.execute("SELECT m.id FROM meetings m JOIN transcript_approval a ON a.meeting_id=m.id WHERE m.state IN ('ready','review_required')").fetchall()
    from reunioes.core import detail
    for row in rows:
        item=detail(root,row['id'])
        if not item['review']['approved']:continue
        folder=root/'reunioes/jobs'/row['id']
        candidates=list(folder.glob('player*.mp4'))+list(folder.glob('chunk-*.wav'))+list((folder/'frames').glob('*.jpg'))
        for path in candidates:
            if not path.resolve().is_relative_to(folder.resolve()) or path.is_symlink():continue
            if now-path.stat().st_mtime<days*86400:continue
            size=path.stat().st_size;path.unlink();freed+=size;count+=1
    return {'freed_bytes':freed,'files':count,'originals_deleted':0}
