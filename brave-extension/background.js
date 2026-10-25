importScripts('local-config.js');
async function signal(tab, active, windowReady=false) {
  const r = await fetch('http://127.0.0.1:58376/api/meet', {
    method: 'POST', headers: {'Content-Type': 'application/json', 'X-Meet-Token': FLOW_MEET_TOKEN},
    body: JSON.stringify({tab: String(tab), active, window_ready:windowReady}), signal: AbortSignal.timeout(4000)
  });
  if (!r.ok) throw new Error('Serviço local indisponível');
  return r.json();
}
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (sender.frameId !== 0 || !sender.tab || !sender.url?.startsWith('https://meet.google.com/') || msg?.type !== 'meet-presence' || typeof msg.active !== 'boolean') return;
  (async()=>{
    const tab=sender.tab.id, title='FLOW Meet - '+tab;
    if(msg.active){
      const win=await chrome.windows.get(sender.tab.windowId);
      if(win.type!=='popup') await chrome.windows.create({tabId:tab,type:'popup',focused:true,width:1280,height:800});
    }
    const result=await signal(tab,msg.active,msg.windowReady===true && sender.tab.title===title);
    reply({...result,capture_title:title});
  })().catch(() => reply({status: 'sem_conexao'}));
  return true;
});
chrome.tabs.onRemoved.addListener(tab => { signal(tab, false).catch(() => {}); });
chrome.tabs.onUpdated.addListener((tab,change)=>{
  if(change.url && !change.url.startsWith('https://meet.google.com/'))signal(tab,false).catch(()=>{});
});
