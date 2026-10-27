"""Sinais de alerta, nunca uma estimativa de acurácia ou revisão humana."""
import re
def assess(transcript):
    result=dict(transcript);rows=result.get('segments') or []
    if not rows:
        result.update(quality='provided',quality_label='Texto fornecido; qualidade do áudio não avaliada',uncertain_count=0,total_count=0)
        return result
    counts={}
    for s in rows:
        text=' '.join(re.findall(r'\w+',s.get('text','').casefold()))
        if text:counts[text]=counts.get(text,0)+1
    checked=[]
    for source in rows:
        s=dict(source);reasons=list(s.get('warnings') or [])
        duration=max(0,float(s.get('end',0))-float(s.get('start',0)))
        words=len(s.get('text','').split());text=' '.join(re.findall(r'\w+',s.get('text','').casefold()))
        if duration>35:reasons.append('Intervalo de fala longo demais; confira o áudio.')
        if duration>15 and words/max(duration,1)<.4:reasons.append('Poucas palavras para esse intervalo de áudio.')
        if text and counts.get(text,0)>=2 and words>=4:reasons.append('Frase repetida; pode ser repetição real ou erro do reconhecimento.')
        if s.get('avg_logprob',0)<-.65:reasons.append('Baixa probabilidade do reconhecimento.')
        if s.get('no_speech_prob',0)>.5:reasons.append('Possível silêncio interpretado como fala.')
        tokens=s.get('words') or []
        if tokens and sum(w.get('probability',1)<.45 for w in tokens)/len(tokens)>.25:reasons.append('Várias palavras com baixa confiança; confira especialmente nomes e números.')
        s['warnings']=list(dict.fromkeys(reasons));s['uncertain']=bool(s.get('uncertain') or reasons)
        checked.append(s)
    rows=checked;result['segments']=rows
    count=sum(bool(s.get('uncertain')) for s in rows);total=len(rows);ratio=count/total
    quality='degraded' if ratio>=.5 else ('uncertain' if ratio>.15 else 'good')
    label={'degraded':'Muitos alertas; confira o áudio','uncertain':'Há trechos para conferir','good':'Rascunho automático; ainda não conferido'}[quality]
    result.update(quality=quality,quality_label=f'{label}. {count} de {total} trechos sinalizados. Isto não mede a precisão.',uncertain_count=count,total_count=total,reviewed=False)
    return result
