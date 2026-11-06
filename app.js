'use strict';



const $=id=>document.getElementById(id);



const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));



const working=new Set(['queued','transcribing','extracting']);



const labels={queued:'Na fila',transcribing:'Transcrevendo',extracting:'Organizando relatório',ready:'A conferir',review_required:'A conferir · há alertas',failed:'Precisa de atenção'};



const app={token:'',page:'library',filter:'all',meetings:[],selected:null,detail:null,tab:'summary',toast:null,loading:false,previewRequested:new Set(),drafts:new Map(),displayedRevision:null};



app.runtime={};app.toolOpen=false;app.vocabularyDirty=false;app.retentionDirty=false;



function modal(title,html,confirmText,callback){$('tool-title').textContent=title;$('tool-body').innerHTML=html;$('tool-confirm').textContent=confirmText;$('tool-confirm').disabled=false;app.toolOpen=true;$('tool-dialog').showModal();$('tool-confirm').onclick=()=>action(async()=>{const b=$('tool-confirm');b.disabled=true;try{await callback();$('tool-dialog').close();app.toolOpen=false;if(app.page==='detail')await loadDetail(true);}finally{b.disabled=false;}});}



$('tool-cancel').onclick=()=>$('tool-dialog').close();$('tool-dialog').addEventListener('close',()=>app.toolOpen=false);



function bytes(n){return (Number(n||0)/1024**3).toFixed(1)+' GB';}



function time(sec){sec=Math.max(0,Math.floor(Number(sec)||0));return(sec>=3600?Math.floor(sec/3600)+':':'')+String(Math.floor(sec/60)%60).padStart(2,'0')+':'+String(sec%60).padStart(2,'0');}



function message(text){$('toast').textContent=text;$('toast').hidden=false;clearTimeout(app.toast);app.toast=setTimeout(()=>$('toast').hidden=true,7000);}



async function post(route,data={}){const r=await fetch('/api/'+route,{method:'POST',headers:{'Content-Type':'application/json','X-Meeting-Token':app.token},body:JSON.stringify(data)});const d=await r.json();if(!r.ok)throw Error(d.error||'Operação não confirmada.');return d;}



async function action(fn){try{await fn();}catch(e){message(e.message);}}



function page(name){
  app.page=name;
  for(const p of ['library','detail','guide','settings'])$(p+'-page').hidden=p!==name;
  document.querySelectorAll('[data-page]').forEach(b=>b.classList.toggle('selected',b.dataset.page===name));
  const titleText={library:'Suas reuniões',detail:'Registro da reunião',guide:'Da conversa ao registro',settings:'Ajustes da reunião'}[name];
  $('page-title').textContent=titleText;
  if(window.pageTitleVapour)window.pageTitleVapour.setText(titleText);
  $('page-subtitle').textContent=name==='detail'?'Ouça, confira e acompanhe as evidências.':'Da conversa ao próximo passo. Com a gravação sempre por perto.';
}



function meetingName(m){if(m.analysis&&m.analysis.title&&!m.analysis.title.startsWith('2026-')&&!m.analysis.title.startsWith('Meet'))return m.analysis.title;if(m.title&&!m.title.startsWith('2026-')&&!m.title.startsWith('Meet ')&&!m.title.startsWith('reuniao-'))return m.title;const match=String(m.title).match(/^Meet\s*[—–-]\s*(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-\d{2}-FLOW$/);return match?'Reunião FLOW · '+match[4]+':'+match[5]:m.title;}
function meetingDate(value,m){const match=String(value||'').match(/^(\d{4})-(\d{2})-(\d{2})$/);const dStr=match?match[3]+'/'+match[2]+'/'+match[1]:String(value||'Data não informada');if(m&&m.meeting_time)return dStr+' · '+m.meeting_time;if(m){const tm=String(m.source||m.title||'').match(/[_sT](\d{2})[-:](\d{2})/);if(tm)return dStr+' · '+tm[1]+':'+tm[2];}return dStr;}
function meetingSortKey(m){const d=String(m.meeting_date||'').match(/^(\d{4})-(\d{2})-(\d{2})/);const tm=m.meeting_time||(String(m.source||m.title||'').match(/[_sT](\d{2})[-:](\d{2})/)||[null,'00','00']).slice(1,3).join(':')||'00:00';if(d)return d[1]+'-'+d[2]+'-'+d[3]+'T'+(tm.length===5?tm+':00':tm);return '1970-01-01T00:00:00';}


function renderLibrary(){



  const query=$('meeting-search').value.toLocaleLowerCase('pt-BR');



  const values=app.meetings.filter(m=>(m.title+' '+m.meeting_date+' '+meetingName(m)+' '+meetingDate(m.meeting_date)).toLocaleLowerCase('pt-BR').includes(query)).filter(m=>{
    if(app.filter==='all')return true;
    if(app.filter==='pending_tasks')return (m.tasks_total>0 && m.tasks_pending>0);
    if(app.filter==='completed_tasks')return (m.tasks_total>0 && m.tasks_pending===0);
    if(app.filter==='working')return working.has(m.state);
    if(app.filter==='review')return !m.reviewed&&!working.has(m.state);
    if(app.filter==='reviewed')return m.reviewed;
    if(app.filter==='recording')return false;
    return true;
  }).sort((a,b)=>{const ka=meetingSortKey(a),kb=meetingSortKey(b);return ka!==kb?kb.localeCompare(ka):(b.created||b.updated||0)-(a.created||a.updated||0);});



  if(app.filter==='recording'){$('meeting-list').innerHTML='<div class="empty"><h2>'+(app.runtime.capture_owned?'Gravação em andamento':'Nenhuma reunião sendo gravada')+'</h2><p>Confira os indicadores de microfone e participantes no topo. Ao sair do Meet, o arquivo aparecerá na biblioteca.</p></div>';return;}



  $('meeting-list').innerHTML=values.length?values.map(m=>{
    let taskBadge='';
    if(m.tasks_total>0){
      if(m.tasks_pending>0){
        taskBadge='<span class="pill warn" style="margin-left:5px;">⚡ '+m.tasks_done+'/'+m.tasks_total+' feitas</span>';
      }else{
        taskBadge='<span class="pill reviewed" style="margin-left:5px;">✓ '+m.tasks_total+'/'+m.tasks_total+' feitas</span>';
      }
    }
    return '<button class="meeting-card" data-meeting="'+esc(m.id)+'"><span role="button" tabindex="0" class="meeting-card-delete-btn" data-delete-id="'+esc(m.id)+'" data-delete-title="'+esc(meetingName(m))+'" title="Excluir reunião permanentemente do disco (Shift+Del)">🗑️</span><span class="pill '+(m.reviewed?'reviewed':working.has(m.state)?'':'warn')+'">'+esc(m.reviewed?'Revisada por você':labels[m.state]||m.state)+'</span>'+taskBadge+'<div class="meeting-source"><b>?</b> Registro da conversa</div><h3>'+esc(meetingName(m))+'</h3><small>'+esc(meetingDate(m.meeting_date, m))+(m.is_test?' · Teste':'')+'</small><span class="card-footer">'+esc(working.has(m.state)?m.progress:m.state==='failed'?(m.reason||'Ver o que precisa de atenção'):'Abrir vídeo, transcrição e relatório')+' ↗</span></button>';
  }).join(''):'<div class="empty"><h2>'+(app.filter==='pending_tasks'?'Nenhuma reunião com tarefas pendentes!':app.filter==='completed_tasks'?'Nenhuma reunião com todas as tarefas feitas ainda.':$('meeting-search').value?'Nenhuma reunião encontrada':'Sua memória de reuniões começa aqui')+'</h2><p class="muted">'+(app.filter==='pending_tasks'?'Todas as tarefas marcadas já foram executadas.':app.filter==='completed_tasks'?'Conclua as tarefas de uma reunião para vê-la aqui.':'Entre no Meet com a extensão FLOW ativa ou importe um arquivo salvo no computador.')+'</p><button id="empty-guide">Ver como funciona</button></div>';



  document.querySelectorAll('.meeting-card-delete-btn').forEach(btn => {
    btn.onclick = (e) => {
      e.stopPropagation();
      confirmDeleteMeeting(btn.dataset.deleteId, btn.dataset.deleteTitle);
    };
  });
  document.querySelectorAll('[data-meeting]').forEach(b=>b.onclick=()=>action(()=>openMeeting(b.dataset.meeting)));if($('empty-guide'))$('empty-guide').onclick=()=>page('guide');if(window.updateMagneticTargets)window.updateMagneticTargets();



}



async function refresh(){



  if(app.loading)return;app.loading=true;



  try{



    const r=await fetch('/api/status');if(!r.ok)throw Error('Serviço local indisponível.');const d=await r.json();app.token=d.token;app.meetings=(d.meetings||[]).sort((a,b)=>{const ka=meetingSortKey(a),kb=meetingSortKey(b);return ka!==kb?kb.localeCompare(ka):(b.created||b.updated||0)-(a.created||a.updated||0);});$('connection').hidden=true;



    app.runtime=d.runtime;
    if(d.ecosystem&&$('stark-live-badge')){
      const st=d.ecosystem.stark_sentinel||{};
      const props=d.ecosystem.pending_proposals||0;
      $('stark-live-badge').textContent=(st.state==='ativo'?'Ativo · Whisper Warm':'Standby')+(props>0?' · '+props+' prop.':'');
    }



    const pendingCount=d.meetings.filter(m=>m.tasks_total>0 && m.tasks_pending>0).length;
    const completedCount=d.meetings.filter(m=>m.tasks_total>0 && m.tasks_pending===0).length;
    if($('count-pending-tasks'))$('count-pending-tasks').textContent=String(pendingCount);
    if($('count-completed-tasks'))$('count-completed-tasks').textContent=String(completedCount);
    if($('count-working'))$('count-working').textContent=String(d.meetings.filter(m=>working.has(m.state)).length);
    if($('count-recording'))$('count-recording').textContent=d.runtime.capture_owned?'1':'0';
    if($('nav-recording-btn'))$('nav-recording-btn').style.display=d.runtime.capture_owned?'flex':'none';



    renderHealth(d.runtime);



    if(!app.vocabularyDirty)$('vocabulary').value=(d.vocabulary||[]).join('\n');



    if(d.storage){const s=d.storage;$('storage-info').textContent=bytes(s.free_bytes)+' livres · '+bytes(s.usage.originals)+' de originais · '+bytes(s.usage.inbox)+' na entrada · '+bytes(s.usage.jobs)+' de processamento.';$('backup-info').textContent=(s.backup?'Último backup: '+new Date(s.backup.at*1000).toLocaleString('pt-BR')+'. ':'Primeiro backup ainda pendente. ')+s.backup_scope;if(!app.retentionDirty)$('retention').value=String(s.policy.derivatives_days);}



    const s=d.runtime.sentinel,states={ativo:'OBS conectado · aguardando Meet',indisponivel:'Gravação indisponível · confira o OBS',gravando:'● Gravando áudio e imagem',aguardando_saida:'Finalizando reunião',finalizando:'Salvando gravação',captura_salva:'Gravação salva',iniciando:'Iniciando captura',detectando_chamada:'Confirmando chamada',atualize_extensao:'Atualize a extensão do Brave',atualizando_janela:'Preparando janela do Meet',obs_em_uso:'OBS sob controle manual',erro:'Confira a captura',desligado:'Captura automática desativada'};



    $('capture-status').textContent=states[s]||'Conferindo captura';$('capture-status').className='pill '+(s==='gravando'?'live':['erro','indisponivel','atualize_extensao','obs_em_uso'].includes(s)?'warn':'');



    const captureWarning=d.runtime.sentinel_reason||d.runtime.capture_recovery_warning;



    $('recording-note').hidden=!captureWarning;if(captureWarning)$('recording-note').textContent=captureWarning;



    $('engine-info').textContent='Reconhecimento: '+(d.asr_label||'Whisper local')+'. Organização: '+d.model+'.';$('runtime-info').textContent=d.runtime.worker+(d.runtime.schedule_error?' · '+d.runtime.schedule_error:'');$('paths').textContent='Gravações: '+d.inbox+'\nMemória: '+d.memory;



    renderLibrary();if(app.page==='detail'&&app.selected)await loadDetail(false);



  }catch(e){$('connection').hidden=false;$('connection').textContent='Não foi possível conectar ao serviço local. As gravações salvas continuam preservadas. '+e.message;}finally{app.loading=false;}



}



function renderHealth(runtime){



  $('audio-health').hidden=!runtime.capture_owned;



  const names={idle:'Parado',unknown:'Sem leitura',active:'Sinal presente',quiet:'Baixo',silence:'Sem sinal há 20s+',clipping:'Volume estourando'};



  for(const [key,stateId,meterId,hintId] of [['microphone','mic-state','mic-meter','mic-hint'],['meeting','meeting-audio-state','meeting-meter','meeting-audio-hint']]){const x=runtime.audio_levels?.[key]||{state:'unknown'};$(stateId).textContent=names[x.state]||'Sem leitura';$(meterId).value=Math.max(-60,x.dbfs??-60);$(hintId).textContent=x.state==='silence'?'Pode ser normal quando ninguém fala. Fale ou peça uma resposta e confira o nível.':x.state==='unknown'?'A captura não forneceu medição recente; confira o OBS.':x.state==='clipping'?'Reduza o ganho do microfone ou volume da chamada.':'Nível do sinal, sem garantia de inteligibilidade.';}



}




function confirmDeleteMeeting(mid, title){
  modal(
    'Excluir reunião permanentemente',
    '<div class="notice error"><strong>Atenção: Ação irreversível (Shift+Del)</strong><br>' +
    'Esta operação vai remover permanentemente do disco o vídeo/áudio original gravado, transcrições, relatório Markdown no Obsidian e todo o histórico desta reunião.</div>' +
    '<p>Deseja realmente apagar <strong>' + esc(title || mid) + '</strong>?</p>',
    'Sim, excluir permanentemente (Shift+Del)',
    async () => {
      await post('delete-meeting', { id: mid });
      message('Reunião e arquivos excluídos permanentemente do disco.');
      if(app.selected === mid){
        app.selected = null;
        page('library');
      }
      await refresh();
    }
  );
}

async function openMeeting(id){const editor=document.querySelector('#segments textarea');if(editor&&app.detail)app.drafts.set(app.detail.id,{index:Number(editor.id.replace('edit-','')),text:editor.value,revision:app.displayedRevision});$('segments').innerHTML='<div class="loading">Abrindo transcrição…</div>';$('report-content').innerHTML='';app.displayedRevision=null;app.selected=id;app.detail=null;app.tab='summary';$('transcript-search').value='';$('only-alerts').checked=false;document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('on',b.dataset.tab==='summary'));$('video').pause();$('video').removeAttribute('src');$('video').load();page('detail');await loadDetail(true);}



async function loadDetail(force){



  const id=app.selected;const r=await fetch('/api/detail?id='+encodeURIComponent(id),{headers:{'X-Meeting-Token':app.token}});const d=await r.json();if(!r.ok)throw Error(d.error);if(id!==app.selected)return;



  const changed=!app.detail||JSON.stringify([d.updated,d.review,d.transcript_revision,d.excerpt_jobs,d.precision,d.analysis_stale,d.state])!==JSON.stringify([app.detail.updated,app.detail.review,app.detail.transcript_revision,app.detail.excerpt_jobs,app.detail.precision,app.detail.analysis_stale,app.detail.state]);app.detail=d;



  $('meeting-title').textContent=meetingName(d);$('meeting-meta').textContent=meetingDate(d.meeting_date, d)+(d.transcript?.duration?' · '+time(d.transcript.duration):'')+(d.is_test?' · Teste':'');



  $('review-status').textContent=d.review.approved?'Revisada por você':'Transcrição não revisada';$('review-status').className='pill '+(d.review.approved?'reviewed':'warn');



  const phase=d.state==='queued'?0:d.state==='transcribing'?1:d.state==='extracting'?2:3;



  $('processing-steps').innerHTML=['Gravação salva','Transcrição','Relatório','Conferência'].map((x,i)=>'<span class="step '+(i<=phase?'done':'')+'">'+(i<phase?'✓ ':'')+x+'</span>').join('');



  let notice='';



  if(working.has(d.state))notice='<div class="notice">'+esc(d.progress||labels[d.state])+'. O processamento acontece neste notebook. Você pode continuar trabalhando.</div>';



  else if(d.state==='failed')notice='<div class="notice error">'+esc(d.reason||'O processamento não terminou.')+' <button id="retry-meeting">Retomar</button></div>';



  else if(d.analysis_stale)notice='<div class="notice warn">O relatório ainda corresponde à versão anterior da transcrição. <button id="rebuild">Atualizar relatório com as correções</button></div>';



  else if(d.transcript)notice='<div class="notice '+(d.transcript.uncertain_count?'warn':'')+'">'+esc(d.transcript.quality_label||'Transcrição automática — confira com o áudio.')+(d.transcript.engine?.includes('base')?' O modelo anterior era leve; use “Transcrever novamente” para gerar outra versão com o modelo maior.':'')+'</div>';



  $('detail-notice').innerHTML=notice;



  if(d.capture_audit?.warning)$('detail-notice').insertAdjacentHTML('afterbegin','<div class="notice warn"><strong>Confira a origem do áudio</strong><br>'+esc(d.capture_audit.warning)+'</div>');



  if($('retry-meeting'))$('retry-meeting').onclick=()=>action(async()=>{await post('retry',{id});await refresh();});



  if($('rebuild'))$('rebuild').onclick=()=>action(async()=>{await post('rebuild-report',{id});message('Relatório será atualizado com suas correções.');await refresh();});



  $('reprocess').disabled=working.has(d.state);$('approve').disabled=!d.transcript||working.has(d.state)||d.review.approved;$('approve').textContent=d.review.approved?'✓ Conferência registrada':'Conferi o áudio e a transcrição';



  $('rebuild-report').disabled=working.has(d.state)||!d.transcript;$('validate-capture').disabled=working.has(d.state)||!d.transcript;



  const metric=d.precision;$('precision-summary').textContent=metric?.reference_words?'Medição nos '+metric.segments+' trechos conferidos: '+(metric.wer*100).toFixed(1)+'% de erros de palavras em '+metric.reference_words+' palavras de referência. Não representa a reunião inteira.':'Precisão ainda não medida. Em um trecho, use “Mais opções → Conferir referência” depois de ouvir a gravação.';



  if(d.preview_ready){if(!$('video').getAttribute('src')){$('video').src='/api/media?id='+encodeURIComponent(id);}$('video').hidden=false;$('player-message').hidden=true;}



  else{$('video').hidden=true;$('player-message').hidden=false;$('player-message').textContent=d.preview_status==='failed'?'Não foi possível preparar o player. Use “Abrir original”.':'Preparando uma cópia local para assistir…';if(!app.previewRequested.has(id)){app.previewRequested.add(id);post('preview',{id}).catch(()=>{});}}



  if((changed||force)&&!document.querySelector('#segments textarea')&&!app.toolOpen){renderSegments();renderReport();}



  $('approve').disabled=!d.transcript||working.has(d.state)||d.review.approved||app.drafts.has(d.id)||!!document.querySelector('#segments textarea')||app.displayedRevision!==d.transcript_revision;



}



function seek(seconds){
  const v=$('video');
  if(v.hidden){message('Aguarde o player ou use “Abrir original”.');return;}
  const sec = Math.max(0, Number(seconds)||0);
  v.currentTime = sec;
  if(v.paused) v.play().catch(()=>{});
  const pc = document.querySelector('.player');
  if(pc){
    const r = pc.getBoundingClientRect();
    if(r.top < 0 || r.bottom > window.innerHeight){
      pc.scrollIntoView({behavior:'smooth', block:'nearest'});
    }
  }
}







function jumpToEvidence(quote, timestamp, area){



  const d = app.detail;



  const segments = d?.transcript?.segments || [];



  let sec = (timestamp != null && timestamp !== '' && timestamp !== 'None') ? Number(timestamp) : null;



  let seg = null;







  if (sec != null && !isNaN(sec)) {



    seg = segments.find(s => s.start <= sec && (s.end >= sec || Math.abs(s.start - sec) < 4)) || segments.find(s => Math.abs(s.start - sec) < 20);



  }







  if (!seg && quote) {



    const qWords = quote.toLowerCase().match(/\b[\wáéíóúâêîôûãõç]+\b/g) || [];



    let bestScore = 0;



    let bestIdx = -1;



    for (let i = 0; i < segments.length; i++) {



      const windowText = (segments[i].text + ' ' + (segments[i+1]?.text || '') + ' ' + (segments[i+2]?.text || '')).toLowerCase();



      let score = 0;



      for (const w of qWords) {



        if (w.length > 2 && windowText.includes(w)) score++;



      }



      if (score > bestScore) {



        bestScore = score;



        bestIdx = i;



      }



    }



    if (bestIdx >= 0 && bestScore >= 2) {



      seg = segments[bestIdx];



      sec = seg.start;



    }



  }







  if (sec != null && !isNaN(sec)) {



    seek(sec);



    if (seg) {



      const segIdx = seg.index ?? segments.indexOf(seg);



      const segEl = document.querySelector(`[data-segment="${segIdx}"]`);



      if (segEl) {



        segEl.scrollIntoView({ behavior: 'smooth', block: 'center' });



        segEl.style.transition = 'all 0.3s ease';



        segEl.style.background = 'rgba(255, 255, 255, 0.15)';



        segEl.style.boxShadow = '0 0 16px rgba(255, 255, 255, 0.4)';



        segEl.style.borderColor = 'var(--accent)';



        setTimeout(() => {



          segEl.style.background = '';



          segEl.style.boxShadow = '';



          segEl.style.borderColor = '';



        }, 4000);



      }



    }



    const prefix = area ? `[${area}] ` : '';



    const preview = seg ? seg.text : quote.slice(0, 60);



    message(`▶ Passando direto para o trecho da reunião (${time(sec)}): ${prefix}"${preview}"`);



  } else {



    message('Esta evidência não foi vinculada a um trecho de áudio; confira sua origem.');



  }



}







function evidence(p){



  const sec = p.timestamp;



  if(p.evidence_state==='ambiguous')return'<details class="evidence"><summary>Citação repetida — escolha a ocorrência</summary><p>'+esc(p.quote)+'</p>'+(p.candidates||[]).map(x=>'<button data-seek="'+Number(x.start)+'">'+time(x.start)+'</button>').join('')+'</details>';



  return'<button class="evidence" '+(sec!=null?'data-seek="'+Number(sec)+'"':'data-quote="'+esc(p.quote)+'"')+'>'+(sec!=null?'▶ '+time(sec)+' · ':'Sem minuto confirmado · ')+esc(p.quote||'')+'</button>';



}







function renderReport(){



  const d=app.detail,a=d?.analysis;if(!a){$('report-content').innerHTML='<p class="muted">O relatório aparecerá aqui após o processamento.</p>';return;}



  let html='';



  if(app.tab==='summary'){



    html='<h2>Resumo da conversa</h2><p class="muted">Síntese automática. Abra as evidências para conferir a origem.</p>';



    if(a.direcionado_para_bruno && a.direcionado_para_bruno.length){
      const totalBruno = a.direcionado_para_bruno.length;
      a.direcionado_para_bruno.forEach((b, idx) => {
        if(b.done === undefined){
          try{
            const localKey = 'flow_bruno_done_' + d.id + '_' + idx;
            if(localStorage.getItem(localKey) === '1') b.done = true;
          }catch(e){}
        }
      });
      const doneBruno = a.direcionado_para_bruno.filter(b => b.done).length;

      html+='<div class="report-block" style="border: 2px solid var(--accent); border-radius: 8px; padding: 14px; margin-bottom: 20px; background: #ffffff08;">'
        + '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">'
        + '<h3 style="color: var(--accent); margin:0; font-size: 1.15em;">🎯 DIRECIONADO PARA BRUNO (' + totalBruno + ' ' + (totalBruno === 1 ? 'ação' : 'ações') + (doneBruno > 0 ? ' · ' + doneBruno + ' executada' + (doneBruno > 1 ? 's' : '') : '') + ')</h3>'
        + (doneBruno > 0 ? '<span class="pill" style="font-size: 11px; padding: 4px 10px; border-color: rgba(255,255,255,0.3); background: rgba(255,255,255,0.08); color: #ffffff;">' + doneBruno + ' de ' + totalBruno + ' executadas</span>' : '<span class="pill" style="font-size: 11px; padding: 4px 10px; color: var(--muted);">' + totalBruno + ' pendentes</span>')
        + '</div>'
        + a.direcionado_para_bruno.map((b, idx) => {
          const sec = b.timestamp != null ? Number(b.timestamp) : '';
          const isDone = !!b.done;
          return '<div class="report-item bruno-card ' + (isDone ? 'is-done' : '') + '" data-seek="' + sec + '" data-quote="' + esc(b.quote || '') + '" data-area="' + esc(b.area || '') + '" style="border-left: 4px solid ' + (isDone ? 'rgba(255,255,255,0.35)' : 'var(--accent)') + '; padding: 12px 14px; margin-bottom: 12px; cursor: pointer; border-radius: 6px; background: var(--canvas); transition: background .16s;" onmouseover="this.style.background=\'var(--raised)\';this.style.transform=\'none\'" onmouseout="this.style.background=\'var(--canvas)\';this.style.transform=\'none\'">'
            + '<div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 6px;">'
            + '<div style="display: flex; align-items: flex-start; gap: 10px; flex: 1;">'
            + '<button type="button" class="bruno-check-btn ' + (isDone ? 'is-done' : '') + '" data-bruno-index="' + idx + '" title="' + (isDone ? 'Desmarcar como executada' : 'Marcar como executada') + '" aria-label="' + (isDone ? 'Desmarcar como executada' : 'Marcar como executada') + '">'
            + '<svg viewBox="0 0 12 10" width="12" height="10" class="bruno-check-svg" style="fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round;"><path d="M1 5l3.5 3.5L11 1"/></svg>'
            + '</button>'
            + '<div style="flex: 1;">'
            + '<strong style="color: var(--accent); font-size: 1.05em; line-height: 1.4;">' + esc(b.area || 'Ação') + ': <span class="bruno-action-text ' + (isDone ? 'is-done-text' : '') + '" style="color: var(--ink); font-weight: normal;">' + esc(b.action || b.description || '') + '</span></strong>'
            + (isDone ? '<span class="bruno-done-pill">✓ Executada</span>' : '')
            + '</div>'
            + '</div>'
            + '<div style="display:flex;align-items:center;gap:6px;flex-shrink:0;">'
            + '<button type="button" class="bruno-dispatch-btn" data-dispatch-index="' + idx + '" style="background:#000000;color:#ffffff;border:1px solid rgba(255,255,255,0.4);padding:3px 10px;border-radius:12px;font-size:0.78em;font-weight:600;cursor:pointer;white-space:nowrap;" title="Despachar diretamente para a Central Maestri e fila do Agente Stark">' + (b.central_task ? '✓ Central (' + esc(b.central_task) + ')' : '⚡ Enviar p/ Stark') + '</button>'
            + (sec !== '' ? '<span style="background: var(--accent); color: var(--canvas); padding: 3px 10px; border-radius: 12px; font-size: 0.82em; font-weight: bold; white-space: nowrap; box-shadow: 0 2px 4px rgba(0,0,0,0.3); flex-shrink: 0;">▶ ' + time(sec) + '</span>' : '<span style="background: var(--raised); color: var(--ink); padding: 3px 10px; border-radius: 12px; font-size: 0.82em; white-space: nowrap; flex-shrink: 0;">▶ Ir ao trecho</span>')
            + '</div>'
            + '</div>'
            + (b.details ? '<p style="margin: 6px 0 8px 32px; font-size: 0.92em; color: var(--ink); line-height: 1.5;' + (isDone ? 'opacity: 0.7;' : '') + '">' + esc(b.details) + '</p>' : '')
            + (b.quote ? '<div style="margin-left: 32px; color: var(--muted); font-style: italic; font-size: 0.88em; padding: 6px 10px; background: rgba(0,0,0,0.25); border-radius: 4px; border-left: 2px solid var(--muted);' + (isDone ? 'opacity: 0.65;' : '') + '">🗣️ "' + esc(b.quote) + '"</div>' : '')
            + '</div>';
        }).join('')
        + '</div>';
    } else if(a.tasks && a.tasks.length){
      const totalBruno = a.tasks.length;
      a.tasks.forEach((b, idx) => {
        if(b.done === undefined){
          try{
            const localKey = 'flow_bruno_done_' + d.id + '_' + idx;
            if(localStorage.getItem(localKey) === '1') b.done = true;
          }catch(e){}
        }
      });
      const doneBruno = a.tasks.filter(b => b.done).length;

      html+='<div class="report-block" style="border: 2px solid var(--accent); border-radius: 8px; padding: 14px; margin-bottom: 20px; background: #ffffff08;">'
        + '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">'
        + '<h3 style="color: var(--accent); margin:0; font-size: 1.15em;">🎯 TAREFAS IDENTIFICADAS (' + totalBruno + ' ' + (totalBruno === 1 ? 'tarefa' : 'tarefas') + (doneBruno > 0 ? ' · ' + doneBruno + ' executada' + (doneBruno > 1 ? 's' : '') : '') + ')</h3>'
        + (doneBruno > 0 ? '<span class="pill" style="font-size: 11px; padding: 4px 10px; border-color: rgba(255,255,255,0.3); background: rgba(255,255,255,0.08); color: #ffffff;">' + doneBruno + ' de ' + totalBruno + ' executadas</span>' : '<span class="pill" style="font-size: 11px; padding: 4px 10px; color: var(--muted);">' + totalBruno + ' pendentes</span>')
        + '</div>'
        + a.tasks.map((b, idx) => {
          const sec = b.timestamp != null ? Number(b.timestamp) : '';
          const isDone = !!b.done;
          return '<div class="report-item bruno-card ' + (isDone ? 'is-done' : '') + '" data-seek="' + sec + '" data-quote="' + esc(b.quote || '') + '" data-area="' + esc(b.owner || 'Tarefa') + '" style="border-left: 4px solid ' + (isDone ? 'rgba(255,255,255,0.35)' : 'var(--accent)') + '; padding: 12px 14px; margin-bottom: 12px; cursor: pointer; border-radius: 6px; background: var(--canvas); transition: background .16s;" onmouseover="this.style.background=\'var(--raised)\';this.style.transform=\'none\'" onmouseout="this.style.background=\'var(--canvas)\';this.style.transform=\'none\'">'
            + '<div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 6px;">'
            + '<div style="display: flex; align-items: flex-start; gap: 10px; flex: 1;">'
            + '<button type="button" class="bruno-check-btn ' + (isDone ? 'is-done' : '') + '" data-bruno-index="' + idx + '" title="' + (isDone ? 'Desmarcar como executada' : 'Marcar como executada') + '" aria-label="' + (isDone ? 'Desmarcar como executada' : 'Marcar como executada') + '">'
            + '<svg viewBox="0 0 12 10" width="12" height="10" class="bruno-check-svg" style="fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round;"><path d="M1 5l3.5 3.5L11 1"/></svg>'
            + '</button>'
            + '<div style="flex: 1;">'
            + '<strong style="color: var(--accent); font-size: 1.05em; line-height: 1.4;">' + esc(b.owner ? b.owner + ': ' : 'Ação: ') + '<span class="bruno-action-text ' + (isDone ? 'is-done-text' : '') + '" style="color: var(--ink); font-weight: normal;">' + esc(b.description || b.action || '') + '</span></strong>'
            + (isDone ? '<span class="bruno-done-pill">✓ Executada</span>' : '')
            + '</div>'
            + '</div>'
            + '<div style="display:flex;align-items:center;gap:6px;flex-shrink:0;">'
            + '<button type="button" class="bruno-dispatch-btn" data-dispatch-index="' + idx + '" style="background:#000000;color:#ffffff;border:1px solid rgba(255,255,255,0.4);padding:3px 10px;border-radius:12px;font-size:0.78em;font-weight:600;cursor:pointer;white-space:nowrap;" title="Despachar diretamente para a Central Maestri e fila do Agente Stark">' + (b.central_task ? '✓ Central (' + esc(b.central_task) + ')' : '⚡ Enviar p/ Stark') + '</button>'
            + (sec !== '' ? '<span style="background: var(--accent); color: var(--canvas); padding: 3px 10px; border-radius: 12px; font-size: 0.82em; font-weight: bold; white-space: nowrap; box-shadow: 0 2px 4px rgba(0,0,0,0.3); flex-shrink: 0;">▶ ' + time(sec) + '</span>' : '<span style="background: var(--raised); color: var(--ink); padding: 3px 10px; border-radius: 12px; font-size: 0.82em; white-space: nowrap; flex-shrink: 0;">▶ Ir ao trecho</span>')
            + '</div>'
            + '</div>'
            + (b.details ? '<p style="margin: 6px 0 8px 32px; font-size: 0.92em; color: var(--ink); line-height: 1.5;' + (isDone ? 'opacity: 0.7;' : '') + '">' + esc(b.details) + '</p>' : '')
            + (b.quote ? '<div style="margin-left: 32px; color: var(--muted); font-style: italic; font-size: 0.88em; padding: 6px 10px; background: rgba(0,0,0,0.25); border-radius: 4px; border-left: 2px solid var(--muted);' + (isDone ? 'opacity: 0.65;' : '') + '">🗣️ "' + esc(b.quote) + '"</div>' : '')
            + '</div>';
        }).join('')
        + '</div>';
    }

    html+=(a.summary_points||[]).length?a.summary_points.map(p=>'<div class="report-item"><p>'+esc(p.description)+'</p>'+evidence(p)+'</div>').join(''):'<div style="white-space:pre-wrap;line-height:1.8">'+esc(a.summary||'Resumo indisponível.')+'</div><p class="warning">Este resumo anterior não tem vínculo por afirmação. Use “Atualizar relatório” para gerar evidências.</p>';



    html+='<div class="report-block"><h3>Tópicos discutidos</h3>'+((a.key_point_evidence||[]).length?a.key_point_evidence.map(p=>'<div class="report-item">'+esc(p.description)+evidence(p)+'</div>').join(''):'<ul>'+(a.key_points||[]).map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul>')+'</div>';



    if((a.analysis_warnings||[]).length)html+='<p class="warning">'+esc(a.analysis_warnings.join(' '))+'</p>';



    if(d.visual)html+='<details class="report-block"><summary>Texto identificado nas imagens</summary><p class="muted">'+esc(d.visual.limitation||'')+'</p><p style="white-space:pre-wrap">'+esc(d.visual.text||'Nenhum texto visual legível identificado.')+'</p></details>';



  }else if(app.tab==='requests'){



    for(const [title,key] of [['Pedidos e requisitos','requests'],['Acordos e compromissos aceitos','agreements'],['Decisões','decisions'],['Dúvidas e definições pendentes','open_questions'],['Pontos de atenção','risks']])html+='<div class="report-block"><h3>'+title+'</h3>'+((a[key]||[]).length?(a[key]||[]).map(p=>'<div class="report-item"><p>'+esc(p.description)+'</p><small>Responsável: '+esc(p.owner||'Não informado')+' · Prazo: '+esc(p.due||'Não informado')+'</small>'+evidence(p)+'</div>').join(''):'<p class="muted">Nenhum item com evidência identificado.</p>')+'</div>';



  }else{



    html='<h2>Ações propostas</h2><p class="muted">Pedidos não são execução automática. Confira a transcrição e a descrição antes de encaminhar uma proposta.</p>';



    if(d.publication_blocked_reason)html+='<div class="notice warn">'+esc(d.publication_blocked_reason)+'</div>';



    html+=(d.proposals||[]).map((p,i)=>'<article class="report-item proposal"><h3>Proposta '+(i+1)+'</h3><textarea id="proposal-'+i+'" aria-label="Descrição da proposta">'+esc(p.description)+'</textarea>'+evidence(p)+'<p><small>Responsável: '+esc(p.owner||'Não informado')+' · Prazo: '+esc(p.due||'Não informado')+'</small></p>'+(p.central_task?'<p>Registrada na Central: '+esc(p.central_task)+'</p>':!d.publication_blocked_reason?'<button class="primary" data-forward="'+esc(p.id)+'" data-index="'+i+'">Revisar envio ao YouTrack</button>':'')+'</article>').join('')||'<p class="muted">Nenhuma tarefa com evidência identificada.</p>';



  }



  $('report-content').innerHTML=html;



  $('report-content').querySelectorAll('.bruno-check-btn').forEach(btn => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const idx = Number(btn.dataset.brunoIndex);
      if (!a.direcionado_para_bruno || !a.direcionado_para_bruno[idx]) return;
      const item = a.direcionado_para_bruno[idx];
      item.done = !item.done;
      try {
        localStorage.setItem('flow_bruno_done_' + d.id + '_' + idx, item.done ? '1' : '0');
      } catch (err) {}
      renderReport();
      if (window.updateMagneticTargets) window.updateMagneticTargets();
      try {
        await post('bruno-action-toggle', { id: d.id, index: idx, quote: item.quote, done: item.done });
      // Sync in-memory meeting task counts immediately
      const foundM = app.meetings.find(m => m.id === d.id);
      if (foundM) {
        const curDone = a.direcionado_para_bruno.filter(b => b.done).length;
        foundM.tasks_done = curDone;
        foundM.tasks_pending = foundM.tasks_total - curDone;
        const pCount = app.meetings.filter(m => m.tasks_total > 0 && m.tasks_pending > 0).length;
        const cCount = app.meetings.filter(m => m.tasks_total > 0 && m.tasks_pending === 0).length;
        if($('count-pending-tasks'))$('count-pending-tasks').textContent = String(pCount);
        if($('count-completed-tasks'))$('count-completed-tasks').textContent = String(cCount);
      }
      } catch (err) {
        console.warn('bruno-action-toggle post failed, saved in localStorage:', err);
      }
    };
  });

  $('report-content').querySelectorAll('.bruno-dispatch-btn').forEach(btn => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const idx = Number(btn.dataset.dispatchIndex);
      const list = a.direcionado_para_bruno || a.tasks || [];
      const item = list[idx];
      if (!item) return;
      btn.disabled = true;
      btn.textContent = 'Enviando…';
      action(async () => {
        const out = await post('dispatch-bruno-action', { id: d.id, index: idx });
        item.central_task = out.task_id;
        renderReport();
        message((out.reused ? 'Ação já vinculada na Central: ' : 'Ação despachada para Stark & Central Maestri: ') + out.task_id);
      });
    };
  });

  $('report-content').querySelectorAll('.bruno-card').forEach(card => {



    card.onclick = () => jumpToEvidence(card.dataset.quote, card.dataset.seek, card.dataset.area);



  });



  $('report-content').querySelectorAll('[data-seek]').forEach(b => {



    if (!b.classList.contains('bruno-card')) {



      b.onclick = (e) => { e.stopPropagation(); jumpToEvidence(b.dataset.quote, b.dataset.seek); };



    }



  });



  $('report-content').querySelectorAll('[data-quote]').forEach(b => {



    if (!b.classList.contains('bruno-card')) {



      b.onclick = (e) => { e.stopPropagation(); jumpToEvidence(b.dataset.quote, b.dataset.seek); };



    }



  });



  $('report-content').querySelectorAll('[data-forward]').forEach(b=>b.onclick=()=>action(async()=>{



    const description=$('proposal-'+b.dataset.index).value,p=await post('proposal-preview',{id:b.dataset.forward,description});



    modal('Prévia para o YouTrack',(p.frozen?'<div class="notice warn">Este pedido tem uma tentativa anterior. O conteúdo abaixo foi preservado para reconciliação e será reutilizado.</div>':'')+'<h3>'+esc(p.title)+'</h3><p>'+esc(p.description)+'</p><blockquote>'+esc(p.quote)+'</blockquote><p>Responsável: '+esc(p.owner)+' · Prazo: '+esc(p.due)+'</p><p>'+esc(p.publication)+'</p>'+(p.duplicates.length?'<div class="notice warn">Possíveis duplicatas locais:<ul>'+p.duplicates.map(x=>'<li>'+esc(x.description)+' · '+esc(x.central_task)+'</li>').join('')+'</ul></div>':'<p>Nenhuma proposta semelhante já encaminhada foi encontrada no histórico local.</p>'),'Confirmar encaminhamento',async()=>{const out=await post('forward',{id:p.id,description:p.description,mode:'auto'});message((out.reused?'Pedido já registrado: ':'Pedido registrado na Central: ')+out.task_id);await loadDetail(true);});



  }));



}



function renderSegments(){



  const d=app.detail;if(!d?.transcript){$('segments').innerHTML='<div class="loading">'+esc(working.has(d?.state)?'Reconhecendo a fala…':'Ainda não há transcrição.')+'</div>';return;}



  const query=$('transcript-search').value.toLocaleLowerCase('pt-BR'),alerts=$('only-alerts').checked;



  $('transcript-info').textContent=(d.transcript.engine||'Reconhecimento local')+' · '+(d.transcript.uncertain_count||0)+' trechos sinalizados';



  let rows=d.transcript.segments||[];



  app.displayedRevision=d.transcript_revision;



  if(!rows.length){$('segments').innerHTML='<div class="segment">'+esc(d.transcript.text||'Nenhum texto reconhecido.')+'</div>';return;}



  $('segments').innerHTML=rows.map((s,i)=>({...s,index:i})).filter(s=>(!alerts||s.uncertain)&&s.text.toLocaleLowerCase('pt-BR').includes(query)).map(s=>'<article class="segment '+(s.uncertain?'flagged':'')+'" data-segment="'+s.index+'"><div class="segment-top"><button class="time" data-play="'+s.start+'">'+time(s.start)+'</button><small>'+esc(s.speaker||'Voz não identificada')+(s.edited_by_user?' · Editado':'')+'</small><button class="edit" data-edit="'+s.index+'">Editar</button></div><div class="segment-text">'+esc(s.text)+'</div>'+((s.warnings||[]).length?'<div class="warning">'+esc(s.warnings.join(' '))+'</div>':s.uncertain?'<div class="warning">Trecho para conferir com o áudio.</div>':'')+'</article>').join('')||'<div class="loading">Nenhum trecho corresponde a esta busca.</div>';



  $('segments').querySelectorAll('[data-play]').forEach(b=>b.onclick=()=>seek(b.dataset.play));



  $('segments').querySelectorAll('[data-segment]').forEach(row=>{



    const i=Number(row.dataset.segment),s=rows[i];



    row.insertAdjacentHTML('beforeend','<details class="segment-options"><summary>Mais opções</summary><button data-voice="'+i+'">Nomear voz</button><button data-reference="'+i+'">Conferir referência</button><button data-asr="'+i+'">Reconhecer só este trecho</button></details>');



    row.querySelector('[data-voice]').onclick=()=>modal('Quem fala neste trecho?','<p>O nome será aplicado somente a este trecho. Outras vozes não serão atribuídas automaticamente.</p><input id="voice-name" aria-label="Nome do participante" maxlength="100" value="'+esc(s.speaker||'')+'">','Salvar nome',async()=>{await post('name-voice',{id:d.id,index:i,name:$('voice-name').value,revision:d.transcript_revision});await loadDetail(true);});



    row.querySelector('[data-reference]').onclick=()=>modal('Referência conferida por você','<p>Ouça o trecho '+time(s.start)+' e escreva exatamente o que foi falado. A medição compara esta referência com o reconhecimento original, sem extrapolar para a reunião inteira.</p><textarea id="reference-text" aria-label="Texto falado conferido">'+esc(s.text)+'</textarea><label><input type="checkbox" id="reference-confirmed"> Ouvi este trecho e conferi este texto com a gravação.</label>','Registrar e medir',async()=>{if(!$('reference-confirmed').checked)throw Error('Ouça e marque a conferência antes de registrar uma referência.');await post('reference',{id:d.id,index:i,text:$('reference-text').value,revision:d.transcript_revision,confirmed:true});message('Referência registrada. Medição restrita à amostra conferida.');await loadDetail(true);});



    row.querySelector('[data-asr]').onclick=()=>action(async()=>{if(app.drafts.has(d.id))throw Error('Salve ou cancele sua correção antes de solicitar outra tentativa.');await post('retry-excerpt',{id:d.id,index:i,revision:d.transcript_revision});message('Trecho na fila. A sugestão aparecerá aqui para comparação.');await loadDetail(true);});



    const jobs=(d.excerpt_jobs||[]).filter(j=>j.segment===i),job=jobs[0];



    if(job){row.insertAdjacentHTML('beforeend','<div class="suggestion"><small>Nova tentativa: '+esc({queued:'Na fila',running:'Reconhecendo',ready:'Sugestão disponível',accepted:'Aplicada por você',failed:'Precisa de atenção'}[job.state]||job.state)+'</small>'+(job.suggestion?'<p>'+esc(job.suggestion)+'</p>':'')+(job.reason?'<p class="warning">'+esc(job.reason)+'</p>':'')+(job.state==='ready'&&job.revision===d.transcript_revision?'<button class="primary" data-accept-asr>Usar esta sugestão</button>':job.state==='ready'?'<p class="warning">Há alterações posteriores. Compare a sugestão e edite manualmente.</p>':'')+'</div>');const accept=row.querySelector('[data-accept-asr]');if(accept)accept.onclick=()=>action(async()=>{await post('accept-excerpt',{job_id:job.id,revision:d.transcript_revision});message('Sugestão aplicada. Atualize o relatório após conferir.');await loadDetail(true);});}



  });



  $('segments').querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>{



    const i=Number(b.dataset.edit),row=b.closest('article');



    row.querySelector('.segment-text').innerHTML='<textarea id="edit-'+i+'" aria-label="Corrigir trecho">'+esc(rows[i].text)+'</textarea><div class="row"><button class="primary" id="save-'+i+'">Salvar correção</button><button id="cancel-'+i+'">Cancelar</button></div>';



    $('approve').disabled=true;



    $('cancel-'+i).onclick=()=>{app.drafts.delete(d.id);renderSegments();$('approve').disabled=d.review.approved||working.has(d.state);};$('edit-'+i).focus();



    $('edit-'+i).oninput=()=>app.drafts.set(d.id,{index:i,text:$('edit-'+i).value,revision:d.transcript_revision});



    $('save-'+i).onclick=()=>action(async()=>{const text=$('edit-'+i).value;app.drafts.set(d.id,{index:i,text,revision:d.transcript_revision});await post('edit-segment',{id:d.id,index:i,text,revision:d.transcript_revision});app.drafts.delete(d.id);row.querySelector('textarea').blur();row.querySelector('textarea').remove();message('Correção salva. Atualize o relatório para refletir o novo texto.');await loadDetail(true);});



  });



  const draft=app.drafts.get(d.id);



  if(draft&&draft.revision===d.transcript_revision){const button=$('segments').querySelector('[data-edit="'+draft.index+'"]');if(button){button.click();$('edit-'+draft.index).value=draft.text;}}



  if(draft&&draft.revision!==d.transcript_revision){$('segments').insertAdjacentHTML('afterbegin','<details class="notice warn"><summary>Rascunho de correção de uma versão anterior</summary><p>O texto abaixo não foi aplicado à nova transcrição.</p><textarea readonly aria-label="Rascunho preservado">'+esc(draft.text)+'</textarea><button id="discard-draft">Descartar este rascunho</button></details>');$('discard-draft').onclick=()=>{app.drafts.delete(d.id);renderSegments();};}



}



$('video').addEventListener('timeupdate',()=>{const t=$('video').currentTime;document.querySelectorAll('[data-segment]').forEach(el=>{const s=app.detail?.transcript?.segments[Number(el.dataset.segment)];el.classList.toggle('current',!!s&&t>=s.start&&t<s.end);});});



$('video').addEventListener('error',()=>{if($('video').getAttribute('src')){$('player-message').hidden=false;$('player-message').textContent='O player não abriu. Atualize a página ou use “Abrir original”.';}});



document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>page(b.dataset.page));document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{app.filter=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('on',x===b));document.querySelectorAll('[data-overview]').forEach(x=>x.classList.toggle('on',x.dataset.overview===app.filter));renderLibrary();});



document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{app.tab=b.dataset.tab;document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('on',x===b));renderReport();});



$('meeting-search').oninput=renderLibrary;$('transcript-search').oninput=renderSegments;$('only-alerts').onchange=renderSegments;$('back').onclick=()=>{$('video').pause();page('library');};



$('approve').onclick=()=>action(async()=>{await post('approve-transcript',{id:app.selected,revision:app.displayedRevision});message('Sua conferência foi registrada.');await loadDetail(true);});



$('reprocess').onclick=()=>action(async()=>{await post('reprocess',{id:app.selected});message('Nova transcrição solicitada. A versão anterior será preservada.');await refresh();});



for(const [id,route] of [['open-original','open-recording'],['open-report','open-note']])$(id).onclick=()=>action(()=>post(route,{id:app.selected}));
if($('copy-whatsapp'))$('copy-whatsapp').onclick=()=>{
  const d=app.detail;if(!d)return;
  const a=d.analysis||{};
  const title=meetingName(d);
  const dt=meetingDate(d.meeting_date,d);
  const actions=a.direcionado_para_bruno||a.tasks||[];
  const sumPoints=(a.summary_points||[]).map(p=>'• '+p.description).join('\n')||(a.summary||'');
  const actLines=actions.map(b=>(b.done?'✅':'⬜')+' *'+(b.area||b.owner||'Ação')+':* '+(b.action||b.description||'')+(b.timestamp!=null?' ('+time(b.timestamp)+')':'')).join('\n');
  const text='*📋 REUNIÃO FLOW: '+title+'*\n📅 '+dt+'\n\n*📝 Resumo Executivo:*\n'+sumPoints+(actLines?'\n\n*🎯 Ações Direcionadas:*\n'+actLines:'');
  navigator.clipboard.writeText(text).then(()=>message('Resumo formatado copiado para o WhatsApp!')).catch(()=>message('Não foi possível copiar automaticamente.'));
};



$('import-toggle').onclick=()=>{$('import-panel').open=!$('import-panel').open;if($('import-panel').open)$('import-path').focus();};



$('import-form').onsubmit=e=>{e.preventDefault();action(async()=>{const item=await post('import',{path:$('import-path').value,title:$('import-title').value,date:$('import-date').value});await post('process');await refresh();await openMeeting(item.id);});};



$('process-queue').onclick=()=>action(async()=>message((await post('process')).state));$('open-obs').onclick=()=>action(()=>post('obs'));$('open-inbox').onclick=()=>action(()=>post('folder',{kind:'inbox'}));$('open-memory').onclick=()=>action(()=>post('folder',{kind:'memory'}));



$('vocabulary').oninput=()=>app.vocabularyDirty=true;$('retention').onchange=()=>app.retentionDirty=true;



$('save-vocabulary').onclick=()=>action(async()=>{await post('vocabulary',{terms:$('vocabulary').value.split('\n').map(x=>x.trim()).filter(Boolean)});app.vocabularyDirty=false;message('Vocabulário salvo para próximas transcrições.');});



$('save-retention').onclick=()=>action(async()=>{await post('storage-policy',{days:Number($('retention').value)});app.retentionDirty=false;message('Regra salva. Originais serão preservados.');await refresh();});



$('backup-now').onclick=()=>action(async()=>{const r=await post('backup');message('Backup local verificado: '+r.files+' arquivos de contexto.');await refresh();});



$('cleanup-now').onclick=()=>action(async()=>{const r=await post('cleanup');message(r.files+' derivados removidos; '+bytes(r.freed_bytes)+' liberados. Originais preservados.');await refresh();});



$('rebuild-report').onclick=()=>action(async()=>{await post('rebuild-report',{id:app.selected});message('Atualização do relatório solicitada.');await refresh();});



if($('delete-meeting'))$('delete-meeting').onclick=()=>{const d=app.detail;if(d)confirmDeleteMeeting(d.id,meetingName(d));};
  $('validate-capture').onclick=()=>{const d=app.detail;modal('Validar uma reunião completa',(d.inspection?'<p>Inspeção do arquivo: '+d.inspection.audio_tracks+' faixa(s) de áudio · '+(d.inspection.has_video?'vídeo presente':'sem faixa de vídeo')+'. Isso não confirma vozes audíveis.</p>':'')+'<p>Use uma nova reunião com outra pessoa. Marque somente o que você confirmou nesta gravação.</p><div class="validation">'+[['own_voice','Ouvi minha voz na gravação'],['remote_voice','Ouvi a voz de outro participante'],['image','A imagem da reunião foi gravada'],['automatic_start','Entrar no Meet iniciou a gravação sozinho'],['automatic_stop','Sair do Meet encerrou e iniciou o processamento']].map(([key,label])=>'<label><input type="checkbox" data-validation="'+key+'"> '+label+'</label>').join('')+'</div><p class="muted">'+(d.validation?.passed?'Esta reunião já tem confirmação registrada.':'Validação real ainda não registrada para esta reunião.')+'</p>','Salvar validação',async()=>{const checks=Object.fromEntries([...document.querySelectorAll('[data-validation]')].map(x=>[x.dataset.validation,x.checked]));const r=await post('validation',{id:d.id,checks,revision:d.transcript_revision});message(r.passed?'Validação real registrada por você.':'Validação parcial registrada; confira os itens pendentes.');await loadDetail(true);});};



document.querySelectorAll('[data-overview]').forEach(b=>b.onclick=()=>{page('library');app.filter=b.dataset.overview;document.querySelectorAll('[data-overview]').forEach(x=>x.classList.toggle('on',x===b));document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('on',x.dataset.filter===app.filter));renderLibrary();});



refresh().then(()=>{
  const urlParamMeeting = new URLSearchParams(window.location.search).get('meeting');
  if(urlParamMeeting) openMeeting(urlParamMeeting);
});setInterval(refresh,6000);





(function initMagneticCursor(){
  if(typeof window==='undefined'||window.matchMedia('(pointer: coarse)').matches)return;
  const cursor=document.getElementById('magnetic-cursor');
  if(!cursor)return;

  let mouseX=-100,mouseY=-100,curX=-100,curY=-100;
  let curW=8,curH=8,curRadius=4;
  let activeClickable=null,visible=false;

  const CLICKABLE_SELECTOR='button,a,.meeting-card,.kinetic-link,.kinetic-status-link,.sidebar-pin-btn,.danger-btn,.pill,input,select,textarea,summary,[data-page],[data-filter],[data-overview],[data-meeting],[data-tab],[role="button"],[role="tab"]';

  window.addEventListener('pointermove',e=>{
    mouseX=e.clientX;mouseY=e.clientY;
    if(!visible){
      visible=true;curX=mouseX;curY=mouseY;
      cursor.classList.add('active');
    }
    const clickable=e.target.closest(CLICKABLE_SELECTOR);
    if(clickable!==activeClickable){
      activeClickable=clickable;
      cursor.classList.toggle('is-framing',!!activeClickable);
    }
    // Liquid glass reflection coordinates
    const card=e.target.closest('.meeting-card');
    if(card){
      const r=card.getBoundingClientRect();
      card.style.setProperty('--mouse-x',(e.clientX-r.left).toFixed(1)+'px');
      card.style.setProperty('--mouse-y',(e.clientY-r.top).toFixed(1)+'px');
    }
  },{passive:true});

  document.addEventListener('mouseleave',()=>{
    cursor.classList.remove('active');
    visible=false;
    activeClickable=null;
  });
  document.addEventListener('mouseenter',()=>{
    cursor.classList.add('active');
    visible=true;
  });

  window.updateMagneticTargets=function(){};

  function loop(){
    if(visible){
      let targetX=mouseX,targetY=mouseY;
      let targetW=8,targetH=8,targetRadius=4;

      if(activeClickable&&activeClickable.isConnected){
        const rect=activeClickable.getBoundingClientRect();
        if(rect.width>0&&rect.height>0){
          const isCard=activeClickable.classList.contains('meeting-card');
          const pad=isCard?6:4;
          // Smooth magnetic pull towards center
          targetX=rect.left+rect.width/2+(mouseX-(rect.left+rect.width/2))*0.15;
          targetY=rect.top+rect.height/2+(mouseY-(rect.top+rect.height/2))*0.15;
          targetW=rect.width+pad*2;
          targetH=rect.height+pad*2;
          const st=window.getComputedStyle(activeClickable);
          targetRadius=(parseFloat(st.borderRadius)||8)+pad;
        }else{
          activeClickable=null;
          cursor.classList.remove('is-framing');
        }
      }

      curX+=(targetX-curX)*0.28;
      curY+=(targetY-curY)*0.28;
      curW+=(targetW-curW)*0.32;
      curH+=(targetH-curH)*0.32;
      curRadius+=(targetRadius-curRadius)*0.32;

      cursor.style.width=curW.toFixed(1)+'px';
      cursor.style.height=curH.toFixed(1)+'px';
      cursor.style.borderRadius=curRadius.toFixed(1)+'px';
      cursor.style.transform='translate3d('+curX.toFixed(1)+'px,'+curY.toFixed(1)+'px,0) translate(-50%,-50%)';
    }
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
})();

// Pinned & Hover Auto-Retractable Sidebar
(function initPinnedSidebar(){
  const shell = document.querySelector('.shell');
  const sidebar = document.querySelector('aside');
  const hoverTrigger = document.getElementById('sidebar-hover-trigger');
  const pinBtn = document.getElementById('sidebar-pin-btn');

  let isPinned = true;
  let leaveTimer = null;

  function setPinned(pinned){
    isPinned = pinned;
    shell.classList.toggle('sidebar-unpinned', !pinned);
    document.body.classList.toggle('sidebar-unpinned', !pinned);
    if(pinBtn){
      pinBtn.classList.toggle('is-pinned', pinned);
      pinBtn.setAttribute('aria-pressed', pinned);
      pinBtn.title = pinned ? 'Desafixar menu (fechar ao retirar o mouse)' : 'Fixar menu na tela';
    }
    
    shell.classList.remove('sidebar-hover-open');
    document.body.classList.remove('sidebar-hover-open');
    try{ localStorage.setItem('flow_sidebar_pinned', pinned ? '1' : '0'); }catch(e){}
  }

  if(pinBtn){
    pinBtn.onclick = (e) => {
      e.stopPropagation();
      setPinned(!isPinned);
    };
  }

  function openHover(){
    if(isPinned) return;
    clearTimeout(leaveTimer);
    shell.classList.add('sidebar-hover-open');
    document.body.classList.add('sidebar-hover-open');
  }

  function closeHover(){
    if(isPinned) return;
    clearTimeout(leaveTimer);
    leaveTimer = setTimeout(() => {
      shell.classList.remove('sidebar-hover-open');
      document.body.classList.remove('sidebar-hover-open');
    }, 280);
  }

  if(hoverTrigger){
    hoverTrigger.addEventListener('mouseenter', openHover);
    hoverTrigger.addEventListener('pointerenter', openHover);
  }
  if(sidebar){
    sidebar.addEventListener('mouseenter', openHover);
    sidebar.addEventListener('pointerenter', openHover);
    sidebar.addEventListener('mouseleave', closeHover);
    sidebar.addEventListener('pointerleave', closeHover);
  }

  // Failsafe global edge-tracking: activates whenever mouse is within 40px of left screen edge
  window.addEventListener('pointermove', e => {
    if(isPinned) return;
    if(e.clientX <= 40){
      openHover();
    }else if(e.clientX > 280 && sidebar && !sidebar.contains(e.target)){
      closeHover();
    }
  }, { passive: true });

  try{
    const saved = localStorage.getItem('flow_sidebar_pinned');
    if(saved === '0'){
      setPinned(false);
    }
  }catch(e){}
})();
