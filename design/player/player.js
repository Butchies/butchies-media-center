'use strict';
(()=>{
const $=id=>document.getElementById(id),v=$('video'),p=$('player'),q=$('queue');
let files=[],index=-1,videoUrl=null,captionUrl=null,lastSave=0;
const fmt=t=>{if(!Number.isFinite(t))return'00:00';let s=Math.floor(t),h=Math.floor(s/3600),m=Math.floor(s%3600/60);return(h?`${h}:`:'')+`${h?String(m).padStart(2,'0'):m}:${String(s%60).padStart(2,'0')}`};
const status=s=>$('status').textContent=s;
const key=()=>index>=0?'bmc-player-position:'+files[index].name+':'+files[index].size+':'+files[index].lastModified:'';
const render=()=>{q.replaceChildren();files.forEach((f,i)=>{const li=document.createElement('li');li.textContent=f.name;li.className=i===index?'active':'';li.tabIndex=0;li.onclick=()=>load(i);li.onkeydown=e=>{if(e.key==='Enter')load(i)};q.append(li)})};
const save=()=>{if(!key()||!Number.isFinite(v.currentTime))return;try{localStorage.setItem(key(),String(v.currentTime))}catch{}};
function load(i){if(i<0||i>=files.length)return;save();if(videoUrl)URL.revokeObjectURL(videoUrl);if(captionUrl){URL.revokeObjectURL(captionUrl);captionUrl=null}v.querySelectorAll('track').forEach(x=>x.remove());$('subtitle').replaceChildren(new Option('Aus','off'));index=i;videoUrl=URL.createObjectURL(files[i]);v.src=videoUrl;v.load();render();status('Geladen: '+files[i].name);v.play().catch(()=>status('Datei geladen. Zum Starten auf ▶ klicken.'))}
function selectFiles(list){const arr=Array.from(list||[]).filter(f=>f.type.startsWith('video/')||f.type.startsWith('audio/')||/\.(mkv|mp4|webm|mov|m4v|mp3|flac)$/i.test(f.name));if(!arr.length){status('Keine unterstützte Mediendatei ausgewählt.');return}files=arr;index=-1;load(0)}
$('openFile').onclick=()=>$('filePicker').click();$('filePicker').onchange=e=>selectFiles(e.target.files);
$('play').onclick=()=>v.paused?v.play().catch(()=>status('Wiedergabe fehlgeschlagen. Codec oder Dateiformat nicht unterstützt.')):v.pause();$('previous').onclick=()=>load(index-1);$('next').onclick=()=>load(index+1);
$('back').onclick=()=>v.currentTime=Math.max(0,v.currentTime-10);$('forward').onclick=()=>v.currentTime=Math.min(v.duration||0,v.currentTime+10);
$('seek').oninput=e=>{if(Number.isFinite(v.duration))v.currentTime=v.duration*(+e.target.value/1000)};
$('mute').onclick=()=>v.muted=!v.muted;$('volume').oninput=e=>{v.volume=+e.target.value;v.muted=false};$('speed').onchange=e=>v.playbackRate=+e.target.value;
$('fullscreen').onclick=()=>document.fullscreenElement?document.exitFullscreen():p.requestFullscreen().catch(()=>status('Vollbild ist hier nicht verfügbar.'));
$('pip').onclick=async()=>{try{if(document.pictureInPictureElement)await document.exitPictureInPicture();else await v.requestPictureInPicture()}catch{status('Bild im Bild wird nicht unterstützt.')}};
$('addSub').onclick=()=>$('subtitlePicker').click();$('subtitlePicker').onchange=e=>{const f=e.target.files?.[0];if(!f)return;if(captionUrl)URL.revokeObjectURL(captionUrl);v.querySelectorAll('track').forEach(x=>x.remove());captionUrl=URL.createObjectURL(f);const t=document.createElement('track');t.kind='subtitles';t.label=f.name;t.srclang='de';t.src=captionUrl;t.default=true;v.append(t);$('subtitle').replaceChildren(new Option('Aus','off'),new Option(f.name,'on'));$('subtitle').value='on';t.track.mode='showing';status('Untertitel geladen: '+f.name)};
$('subtitle').onchange=e=>Array.from(v.textTracks).forEach(t=>t.mode=e.target.value==='on'?'showing':'disabled');
$('subToggle').onclick=()=>{$('subtitle').value=$('subtitle').value==='off'&&$('subtitle').options.length>1?'on':'off';$('subtitle').dispatchEvent(new Event('change'))};
$('offset').onchange=()=>status('Untertitelversatz ist in dieser Browser-Vorschau nicht implementiert.');
v.addEventListener('loadedmetadata',()=>{let pos=0;try{pos=Number(localStorage.getItem(key()))||0}catch{}if(pos>0&&pos<v.duration-5)v.currentTime=pos});
v.addEventListener('timeupdate',()=>{$('seek').value=Number.isFinite(v.duration)&&v.duration>0?Math.round(v.currentTime/v.duration*1000):0;$('clock').textContent=fmt(v.currentTime)+' / '+fmt(v.duration);if(Date.now()-lastSave>3000){lastSave=Date.now();save()}});
v.addEventListener('play',()=>{$('play').textContent='⏸';status('Wiedergabe läuft')});v.addEventListener('pause',()=>{$('play').textContent='▶';save()});v.addEventListener('volumechange',()=>{$('mute').textContent=v.muted||v.volume===0?'🔇':'🔊'});
v.addEventListener('ended',()=>{save();if($('autonext').checked&&index<files.length-1)load(index+1);else status('Wiedergabe beendet')});v.addEventListener('error',()=>status('Wiedergabe nicht möglich: Der Browser unterstützt diese Datei oder ihren Codec möglicherweise nicht.'));
document.addEventListener('keydown',e=>{if(['INPUT','SELECT','TEXTAREA','BUTTON'].includes(document.activeElement?.tagName))return;if(e.code==='Space'){e.preventDefault();$('play').click()}else if(e.key==='ArrowLeft')$('back').click();else if(e.key==='ArrowRight')$('forward').click();else if(e.key.toLowerCase()==='f')$('fullscreen').click();else if(e.key.toLowerCase()==='m')$('mute').click();else if(e.key.toLowerCase()==='n')$('next').click()});
window.addEventListener('beforeunload',()=>{save();if(videoUrl)URL.revokeObjectURL(videoUrl);if(captionUrl)URL.revokeObjectURL(captionUrl)});
})();
