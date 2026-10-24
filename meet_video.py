"""OBS captura a janela dedicada do Meet; nunca usa a tela inteira como fallback."""
import time

def prepare(obs,tab):
    scene='Reunião FLOW';name='Meet FLOW — janela dedicada'
    title='FLOW Meet - '+tab
    items=obs.call('GetInputList')['inputs']
    if not any(i['inputName']==name for i in items):
        obs.call('CreateInput',{'sceneName':scene,'inputName':name,'inputKind':'window_capture','inputSettings':{},'sceneItemEnabled':False})
    choices=obs.call('GetInputPropertiesListPropertyItems',{'inputName':name,'propertyName':'window'}).get('propertyItems',[])
    match=[p['itemValue'] for p in choices if p.get('itemEnabled',True) and p.get('itemValue','').split(':')[0] in (title,title+' - Brave') and p.get('itemValue','').lower().endswith(':brave.exe')]
    if len(match)!=1:raise ValueError('Aguardando janela dedicada do Meet; recarregue a extensão e a aba.')
    obs.call('SetInputSettings',{'inputName':name,'inputSettings':{'window':match[0],'priority':0,'method':2,'client_area':True,'cursor':True},'overlay':True})
    obs.call('SetCurrentProgramScene',{'sceneName':scene})
    for item in obs.call('GetSceneItemList',{'sceneName':scene})['sceneItems']:
        if item.get('inputKind') in ('monitor_capture','window_capture'):
            obs.call('SetSceneItemEnabled',{'sceneName':scene,'sceneItemId':item['sceneItemId'],'sceneItemEnabled':item['sourceName']==name})
        if item['sourceName']==name:
            video=obs.call('GetVideoSettings')
            obs.call('SetSceneItemTransform',{'sceneName':scene,'sceneItemId':item['sceneItemId'],'sceneItemTransform':{'positionX':0.0,'positionY':0.0,'boundsType':'OBS_BOUNDS_SCALE_INNER','boundsWidth':float(video['baseWidth']),'boundsHeight':float(video['baseHeight']),'boundsAlignment':0,'alignment':5}})
    audio_name='Meet FLOW — áudio Brave'
    if not any(i['inputName']==audio_name for i in items):
        obs.call('CreateInput',{'sceneName':scene,'inputName':audio_name,'inputKind':'wasapi_process_output_capture','inputSettings':{'window':match[0],'priority':0,'exclude_process_tree':False},'sceneItemEnabled':True})
    else:
        obs.call('SetInputSettings',{'inputName':audio_name,'inputSettings':{'window':match[0],'priority':0,'exclude_process_tree':False},'overlay':True})
        for item in obs.call('GetSceneItemList',{'sceneName':scene})['sceneItems']:
            if item['sourceName']==audio_name:obs.call('SetSceneItemEnabled',{'sceneName':scene,'sceneItemId':item['sceneItemId'],'sceneItemEnabled':True})
    # Do not mix unrelated desktop applications into the meeting's audio source.
    obs.call('SetInputMute',{'inputName':'Áudio da reunião','inputMuted':True})
    for audio in ('Meu microfone',audio_name):
        obs.call('SetInputMute',{'inputName':audio,'inputMuted':False})
        # Faixa 1 = mix para player/ASR; 2 = microfone; 3 = participantes Brave.
        obs.call('SetInputAudioTracks',{'inputName':audio,'inputAudioTracks':{str(n):n==1 or n==(2 if audio=='Meu microfone' else 3) for n in range(1,7)}})
    # Simple mode suporta múltiplas faixas com qualidade distinta de Same as stream.
    obs.call('SetProfileParameter',{'parameterCategory':'SimpleOutput','parameterName':'RecTracks','parameterValue':'7'})
    # Allow Windows Graphics Capture a frame before starting the encoder.
    time.sleep(0.5)
