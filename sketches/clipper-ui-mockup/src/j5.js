/* ============ IMAGE LAYERS (FRAME & OVERLAY) ============ */
/* Bridge `list_frames()` mengirim `frame_url` (file:// ke frame.png) dan
   `thumbnail_url`. TIDAK ADA field bernama `url` — memakai `f.url` menghasilkan
   undefined, `setFrameImg(undefined)` menyembunyikan lapisan, dan frame yang diklik
   di Library tidak pernah muncul di preview tengah (bug P1.1 di bug.txt).
   Semua pembacaan URL frame WAJIB lewat helper ini. */
function frameUrl(f){
 if(!f)return '';
 return f.frame_url||f.url||'';
}

function setFrameImg(url){
 document.querySelectorAll('.rc').forEach(rc=>{
  let img=rc.querySelector('.frameimg');
  if(url){
   if(!img){
    img=document.createElement('img');
    img.className='frameimg';
    rc.appendChild(img);
   }
   if(img.getAttribute('src')!==url)img.setAttribute('src',url);
   img.style.display='';
  } else if(img){
   img.style.display='none';
   img.removeAttribute('src');
  }
 });
}

function setOverlayImg(url){
 document.querySelectorAll('.rc .ic').forEach(ic=>{
  let img=ic.querySelector('img');
  if(url){
   if(!img){
    img=document.createElement('img');
    ic.appendChild(img);
   }
   if(img.getAttribute('src')!==url)img.setAttribute('src',url);
   ic.classList.remove('empty');
  } else {
   if(img)img.remove();
   ic.classList.add('empty');
  }
 });
}

/* ============ PRESET <-> STATE ============ */
function buildPreset(){
 return {
  canvas:{w:CW,h:CH,id:S.canvasId},
  frame:{id:S.frame||'',path:''},
  video:{scale:+S.video.scale.toFixed(4),x:Math.round(+S.video.x||0),y:Math.round(S.video.y),
         radius:Math.round(S.video.radius),aspect:S.video.aspect,
         blur_background:!!S.video.blurOn, blur_radius:Math.round(+S.video.blur||40)},
  subtitle:{font:S.sub.font,size:Math.round(S.sub.size),y:Math.round(S.sub.y),
   align:S.sub.align||'center',max_lines:Math.max(1,S.sub.maxLines|0),
   line_spacing:+(+S.sub.lineSpacing||-0.15).toFixed(3),
   outline:Math.round(Math.abs(S.sub.outline)),outline_mode:S.sub.outlineMode||'outer',
   outline_color:S.sub.outlineColor||'',
   shadow_enabled:!!S.sub.shadowOn,
   shadow_x:Math.round(S.sub.shadowX),shadow_y:Math.round(S.sub.shadowY),
   shadow_color:hex(S.sub.shadowColor),shadow_blur:Math.round(S.sub.shadowBlur),
   layer_order:S.sub.layerOrder||'shadow-stroke-fill',
   color:hex(S.sub.color),active_color:hex(S.sub.active),
   animation:S.sub.anim,words_per_line:Math.max(1,S.sub.wpl|0)},
  headline:{enabled:!!S.head.on,text:S.head.text,gemini_default:false,font:S.head.font,
   size:Math.round(S.head.size),x:Math.round(S.head.x),y:Math.round(S.head.y),
   max_lines:Math.max(1,S.head.maxLines|0),align:S.head.align||'center',
   line_spacing:+(+S.head.lineSpacing||-0.25).toFixed(3),
   outline:Math.round(Math.abs(S.head.outline)),outline_mode:S.head.outlineMode||'outer',
   outline_color:S.head.outlineColor||'',
   shadow_enabled:!!S.head.shadowOn,
   shadow_x:Math.round(S.head.shadowX),shadow_y:Math.round(S.head.shadowY),
   shadow_color:hex(S.head.shadowColor),shadow_blur:Math.round(S.head.shadowBlur),
   layer_order:S.head.layerOrder||'shadow-stroke-fill',
   color:hex(S.head.color)},
  watermark:{enabled:!!S.wm.on,text:S.wm.text,font:S.wm.font,size:Math.round(S.wm.size),
   x:Math.round(S.wm.x),y:Math.round(S.wm.y),max_lines:1,align:S.wm.align||'center',
   outline:Math.round(Math.abs(S.wm.outline)),outline_mode:S.wm.outlineMode||'outer',
   outline_color:S.wm.outlineColor||'',
   shadow_enabled:!!S.wm.shadowOn,
   shadow_x:Math.round(S.wm.shadowX),shadow_y:Math.round(S.wm.shadowY),
   shadow_color:hex(S.wm.shadowColor),shadow_blur:Math.round(S.wm.shadowBlur),
   layer_order:S.wm.layerOrder||'shadow-stroke-fill',
   color:hex(S.wm.color)},
  custom_png:{enabled:!!S.png.on,path:S.png.path||'',
   x:Math.round(S.png.x),y:Math.round(S.png.y),width:Math.round(S.png.w),
   opacity:+(+S.png.opacity).toFixed(3)},
  intro:{enabled:!!S.intro.on,
   duration:+(+S.intro.dur||0.4).toFixed(2),
   fade:+(+S.intro.fade||0).toFixed(2),
   background:S.intro.bg||'',
   show_headline:!!S.intro.head,
   show_creator:!!S.intro.wm},
  export:{w:CW,h:CH,crf:S.exp.crf|0,preset:S.exp.preset}
 }}

function applyPreset(p){
 if(!p||typeof p!=='object')return;
 const c=p.canvas||{}; CW=+c.w||CW; CH=+c.h||CH;
 S.canvasId=c.id||(_canvases.find(x=>x.w===CW&&x.h===CH)||{}).id||S.canvasId;
 S.frame=(p.frame||{}).id||'';
 const v=p.video||{};
 S.video={scale:+v.scale||1,x:+v.x||0,y:+v.y||0,radius:+v.radius||0,aspect:v.aspect||'16/9',
          blurOn:!!v.blur_background, blur:+v.blur_radius||40};
 const shadowIn=(b,defOff)=>{
  const legacy=(+b.shadow||0);
  return {shadowOn:b.shadow_enabled!==false,
   shadowX:(b.shadow_x===undefined?(legacy||defOff):+b.shadow_x),
   shadowY:(b.shadow_y===undefined?(legacy||defOff):+b.shadow_y),
   shadowColor:b.shadow_color||'#000000',
   shadowBlur:+b.shadow_blur||0,
   layer_order:b.layer_order||'shadow-stroke-fill'}};
 const s=p.subtitle||{};
 S.sub=Object.assign({font:s.font||'subtitle.ttf',size:+s.size||80,y:+s.y||0,
  align:s.align||'center',maxLines:Math.max(1,+s.max_lines||2),
  lineSpacing:(s.line_spacing===undefined?-0.15:
    (Math.abs(+s.line_spacing)<=1?+s.line_spacing:+s.line_spacing/86)),
  outline:+s.outline||0,
  outlineMode:s.outline_mode||'outer',outlineColor:s.outline_color||'',
  color:s.color||'#FFFFFF',active:s.active_color||'#FFA500',
  anim:s.animation||'none',
  wpl:(function(v){v=+v||0; if(v<=0)return 3; if(v<=1)return 1; if(v<=4)return 3; return 5})(s.words_per_line),
  autoText:S.sub.autoText,text:S.sub.text},shadowIn(s,3));
 if(S.sub.autoText!==false)S.sub.text=sampleSubText(S.sub.wpl);
 const h=p.headline||{};
 S.head=Object.assign({on:h.enabled!==false,text:h.text||S.head.text,
  font:h.font||'title.ttf',size:+h.size||86,
  x:+h.x||45,y:+h.y||55,maxLines:Math.max(1,+h.max_lines||2),align:h.align||'center',
  lineSpacing:(h.line_spacing===undefined?-0.25:
    (Math.abs(+h.line_spacing)<=1?+h.line_spacing:+h.line_spacing/86)),
  outline:+h.outline||0,outlineMode:h.outline_mode||'outer',
  outlineColor:h.outline_color||'',color:h.color||'#FFFFFF'},shadowIn(h,8));
 const w=p.watermark||{};
 S.wm=Object.assign({on:w.enabled!==false,text:w.text||S.wm.text,
  font:w.font||'title.ttf',size:+w.size||130,
  x:+w.x||45,y:+w.y||55,align:w.align||'center',outline:+w.outline||0,outlineMode:w.outline_mode||'outer',
  outlineColor:w.outline_color||'',color:w.color||'#D94B0A'},shadowIn(w,6));
 const g=p.custom_png||{};
 S.png={on:!!g.enabled,name:(g.path||'').split('/').pop()||'',path:g.path||'',url:'',
  x:+g.x||0,y:+g.y||0,w:+g.width||220,
  opacity:(g.opacity===undefined||g.opacity===null)?1:Math.max(0,Math.min(1,+g.opacity))};
 if(S.png.path&&B&&B.overlay_url){B.overlay_url(S.png.path,u=>{if(u){S.png.url=u;setOverlayImg(u);renderOverlayList()}
  else{S.png.on=false;S.png.url='';syncAll();buildInspector();toast(L('pngMissing'))}})}
 else setOverlayImg('');
 const e=p.export||{};
 S.exp={crf:(e.crf===undefined?18:+e.crf),preset:e.preset||'medium'};
 // Intro Cover (item 12). Preset lama tanpa blok `intro` -> tetap mati, aman.
 const ic=p.intro||{};
 S.intro={on:!!ic.enabled,
  dur:(ic.duration===undefined?0.4:Math.max(0.05,+ic.duration||0.4)),
  fade:(ic.fade===undefined?0.15:Math.max(0,+ic.fade||0)),
  bg:ic.background||'',bgUrl:'',
  head:ic.show_headline!==false,wm:ic.show_creator!==false};
 // Gambar cover disimpan sebagai path relatif di preset; URL file:// untuk preview
 // diminta ke host, sama caranya dengan stiker overlay.
 if(S.intro.bg&&B&&B.overlay_url){
  B.overlay_url(S.intro.bg,u=>{S.intro.bgUrl=u||''; if(!u)S.intro.bg=''; buildInspector()});
 }
 
 const curF=_frames.find(x=>x.id===S.frame);
 if(curF)setFrameImg(frameUrl(curF));

 computeRC(); syncAll(); buildInspector(); renderFrames(); renderThemes(); renderOverlayList();
}

function loadFrames(){
 if(!(B&&B.list_frames)){renderFrames();return}
 B.list_frames(js=>{let d=[];try{d=JSON.parse(js)}catch(e){}
  if(!Array.isArray(d)){toast(L('failed')+((d&&d.error)||'?'));return}
  _frames=d;
  let cur=null;
  if(S.frame&&_frames.some(x=>x.id===S.frame)){
   cur=_frames.find(x=>x.id===S.frame);
  } else if(_frames[0]){
   S.frame=_frames[0].id;
   cur=_frames[0];
  }
  if(cur)setFrameImg(frameUrl(cur));
  renderFrames();
  syncAll();
 });
}

function renderFrames(){
 const box=$('frameGrid'); if(!box)return;
 if(!_frames.length){box.innerHTML='<div class="empty">'+L('noFrame')+'</div>';return}
 box.innerHTML=_frames.map(f=>{
  const on=f.id===S.frame;
  const desc=(f.tags&&f.tags.length)?f.tags.join(', '):'';
  return '<button class="card'+(on?' on':'')+'" onclick="pickFrame(\''+f.id+'\')">' +
   trashBtn("event.stopPropagation();delFrame('"+f.id+"')",L('trash')) +
   '<span class="th" style="background-image:url(\''+f.thumbnail_url+'\')">' +
   '<span class="center-overlay">' +
   '<b>'+f.name+'</b>' +
   (desc?'<small>'+desc+'</small>':'') +
   '</span></span>' +
   '</button>';
 }).join('');
}

function pickFrame(id){
 const f=_frames.find(x=>x.id===id);
 S.frame=id;
 setFrameImg(frameUrl(f));
 renderFrames();
 syncAll();
}

function importFrame(){
 if(!(B&&B.import_frame_dialog)){toast(L('guiOnly'));return}
 B.import_frame_dialog(js=>{let r={};try{r=JSON.parse(js)}catch(e){}
  if(r.error){toast(L('failed')+r.error);return}
  if(r.id){loadFrames();pickFrame(r.id)}});
}

function delFrame(id){
 const f=_frames.find(x=>x.id===id),nm=f?f.name:id;
 const go=()=>B.delete_frame(id,js=>{let r={};try{r=JSON.parse(js)}catch(e){}
  if(r.error){toast(L('failed')+r.error);return}
  if(S.frame===id){S.frame='';setFrameImg('')}
  loadFrames();toast(L('frameDeleted')+nm)});
 if(!(B&&B.delete_frame)){toast(L('guiOnly'));return}
 B.confirm?B.confirm(L('askDelFrame')+'\n\n'+nm,ok=>{if(ok)go()}):(confirm(L('askDelFrame'))&&go());
}

function loadCanvases(){
 if(!(B&&B.list_canvases)){setCanvasSize('9x16');return}
 B.list_canvases(js=>{let d=[];try{d=JSON.parse(js)}catch(e){}
  _canvases=Array.isArray(d)&&d.length?d:[{id:'9x16',label:'9:16',w:1080,h:1920,ratio:'9:16'}];
  setCanvasSize(S.canvasId);
 });
}

function loadActivePreset(){
 if(!(B&&B.active_preset)){_booting=false;return}
 B.active_preset(js=>{let d={};try{d=JSON.parse(js)}catch(e){}
  if(d&&d.canvas)applyPreset(d);
  _booting=false;
 });
}
