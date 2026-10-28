"""Retoma checkpoints locais e inventaria somente a pasta dedicada de entrada."""
import time
from pathlib import Path
from reunioes.core import db,read,save,ingest,EXT

def recover_jobs(root):
    count=0
    with db(root) as c:
        for row in c.execute("SELECT id FROM meetings WHERE state IN ('transcribing','extracting')").fetchall():
            path=Path(root)/'reunioes/jobs'/row['id']/'recovery.json'
            attempts=read(path).get('attempts',0) if path.exists() else 0
            save(path,{'attempts':attempts+1,'at':time.time(),'reason':'service_restart'})
            state='queued' if attempts<3 else 'failed'
            c.execute('UPDATE meetings SET state=?,progress=?,reason=?,updated=? WHERE id=?',
                      (state,'Recuperando checkpoint após reinício' if state=='queued' else 'Conferir falha recorrente',
                       '' if state=='queued' else 'Três recuperações interrompidas; confira antes de retomar.',time.time(),row['id']))
            count+=state=='queued'
    return count

def scan_closed(root):
    count=0
    for p in (Path(root)/'reunioes/entrada').iterdir():
        if not p.is_file() or p.suffix.lower() not in EXT:continue
        stat=p.stat()
        if not stat.st_size or time.time()-stat.st_mtime<5:continue
        try:
            result=ingest(root,p)
            if not result.get('reused'):count+=1
        except (ValueError,OSError):continue
    return count
