"""Níveis observados no OBS. Silêncio e falta de telemetria não são equivalentes."""
import math,threading

class AudioHealth:
    names={'microphone':'Meu microfone','meeting':'Meet FLOW — áudio Brave'}
    def __init__(self):self.samples={};self.lock=threading.Lock()
    def observe(self,name,levels,now):
        if name not in self.names.values():return
        values=[float(channel[1]) for channel in levels if len(channel)>1]
        if not values:return
        peak=max(values)
        if not math.isfinite(peak):return
        with self.lock:
            old=self.samples.get(name,{})
            since=old.get('silent_since')
            self.samples[name]={'peak':peak,'at':now,'silent_since':(now if since is None else since) if peak<.0018 else None}
    def snapshot(self,now,recording):
        out={}
        with self.lock:
            for key,name in self.names.items():
                s=self.samples.get(name)
                if not recording:state='idle'
                elif not s or now-s['at']>10:state='unknown'
                elif s['peak']>=.99:state='clipping'
                elif s['silent_since'] is not None and now-s['silent_since']>=20:state='silence'
                else:state='active' if s['peak']>=.0018 else 'quiet'
                out[key]={'name':name,'state':state,'dbfs':round(20*math.log10(max(s['peak'],.000001)),1) if s else None,
                          'silent_seconds':round(now-s['silent_since']) if s and s['silent_since'] is not None else 0}
        return out
