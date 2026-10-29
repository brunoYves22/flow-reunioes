"""Rastreabilidade literal e difusa com fallback de janela de palavras."""
import json, re
from reunioes.core import norm, db

def locate(quote, segments):
    if not quote or not segments:
        return {'timestamp': None, 'end_timestamp': None, 'evidence_state': 'unlocated', 'candidates': []}

    q_norm = norm(quote)
    text = ''
    spans = []
    for s in segments:
        value = norm(s.get('text', ''))
        if not value:
            continue
        if text:
            text += ' '
        start = len(text)
        text += value
        spans.append((start, len(text), s))

    hits = []
    offset = 0
    while q_norm:
        pos = text.find(q_norm, offset)
        if pos < 0:
            break
        rows = [s for a, b, s in spans if b > pos and a < pos + len(q_norm)]
        if rows:
            hits.append({'start': rows[0].get('start'), 'end': rows[-1].get('end')})
        offset = pos + 1

    if hits:
        return {
            'timestamp': hits[0]['start'] if len(hits) == 1 else None,
            'end_timestamp': hits[0]['end'] if len(hits) == 1 else None,
            'evidence_state': 'located' if len(hits) == 1 else 'ambiguous',
            'candidates': hits if len(hits) > 1 else []
        }

    # Fallback difuso: sobreposição de palavras por janela de segmentos
    stopwords = {
        'a', 'o', 'as', 'os', 'um', 'uma', 'de', 'do', 'da', 'dos', 'das', 'em', 'no', 'na', 'nos', 'nas',
        'por', 'para', 'pra', 'pro', 'com', 'e', 'que', 'se', 'mas', 'ou', 'foi', 'tem', 'vai', 'tá', 'né', 'aí'
    }
    q_words = [w for w in re.findall(r'\b\w+\b', q_norm) if len(w) > 2 and w not in stopwords]
    if not q_words:
        q_words = [w for w in re.findall(r'\b\w+\b', q_norm) if len(w) > 1]

    if q_words:
        best_score = 0
        best_start = None
        best_end = None
        for i in range(len(segments)):
            window_segs = segments[i:min(len(segments), i + 3)]
            w_text = norm(" ".join(s.get('text', '') for s in window_segs))
            w_words = set(re.findall(r'\b\w+\b', w_text))
            matches = sum(1 for w in q_words if w in w_words)
            score = matches / len(q_words)
            if matches >= 3 and score > best_score:
                best_score = score
                best_start = window_segs[0].get('start')
                best_end = window_segs[-1].get('end')

        if best_score >= 0.25 and best_start is not None:
            return {
                'timestamp': best_start,
                'end_timestamp': best_end,
                'evidence_state': 'located',
                'candidates': []
            }

    return {'timestamp': None, 'end_timestamp': None, 'evidence_state': 'unlocated', 'candidates': []}

def attach(analysis, transcript):
    out = dict(analysis)
    for key in ('summary_points', 'key_point_evidence', 'tasks', 'decisions', 'risks', 'next_steps', 'requests', 'agreements', 'open_questions', 'direcionado_para_bruno'):
        out[key] = [{**p, **locate(p.get('quote', ''), transcript.get('segments', []))} for p in analysis.get(key, []) if isinstance(p, dict)]
    return out

def submitted_description(submitted):
    if not submitted:
        return None
    request = json.loads(submitted).get('request', '')
    return request.split('Proposta revisada: ', 1)[1].split('\nCitação de origem', 1)[0].strip() if 'Proposta revisada: ' in request else None

def proposal_preview(root, pid, description):
    if not isinstance(description, str) or not 1 <= len(description.strip()) <= 5000:
        raise ValueError('Revise a descrição.')
    with db(root) as c:
        row = c.execute('SELECT p.*,m.title,m.meeting_date FROM proposals p JOIN meetings m ON m.id=p.meeting_id WHERE p.id=?', (pid,)).fetchone()
        if not row:
            raise ValueError('Proposta não encontrada.')
        others = c.execute('SELECT id,payload,central_task,submitted_payload FROM proposals WHERE id<>? AND central_task IS NOT NULL', (pid,)).fetchall()
    p = json.loads(row['payload'])
    words = set(re.findall(r'\w+', norm(description)))
    duplicates = []
    frozen = submitted_description(row['submitted_payload'])
    requested_description = description
    if frozen:
        description = frozen
        words = set(re.findall(r'\w+', norm(description)))
    for other in others:
        candidate = json.loads(other['payload'])
        sent = submitted_description(other['submitted_payload'])
        if sent:
            candidate['description'] = sent
        w = set(re.findall(r'\w+', norm(candidate['description'])))
        similarity = len(words & w) / max(1, len(words | w))
        if similarity >= .65:
            duplicates.append({'id': other['id'], 'description': candidate['description'], 'central_task': other['central_task'], 'similarity': round(similarity, 2)})
    return {
        'id': pid,
        'title': '[' + row['meeting_date'] + '] ' + row['title'],
        'description': description.strip(),
        'quote': p.get('quote', ''),
        'timestamp': p.get('timestamp'),
        'owner': p.get('owner') or 'Não informado',
        'due': p.get('due') or 'Não informado',
        'duplicates': duplicates,
        'remote_checked': False,
        'already_forwarded': row['central_task'],
        'frozen': bool(row['submitted_payload']),
        'requested_differs': bool(frozen and norm(frozen) != norm(requested_description)),
        'publication': 'O orquestrador pesquisa duplicidades no YouTrack antes de publicar. Esta prévia consulta o histórico local.'
    }
