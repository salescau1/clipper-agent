/* ============ IKON ============
   Tombol hapus item memakai ikon TEMPAT SAMPAH merah, bukan huruf "×" (bug.txt P4.20).
   Satu sumber ikon supaya kartu Frame, Theme, Sticker, dan baris Font tidak pernah
   berbeda bentuk. */
const ICON_TRASH='<svg width="12" height="12" viewBox="0 0 14 14" aria-hidden="true">'+
 '<g fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round">'+
 '<path d="M2.5 4h9"/><path d="M5.6 4V2.6h2.8V4"/>'+
 '<path d="M3.6 4l.6 7.2a.8.8 0 0 0 .8.7h4a.8.8 0 0 0 .8-.7L10.4 4"/>'+
 '<path d="M6 6.3v4"/><path d="M8 6.3v4"/></g></svg>';
/* Elemen SPAN, bukan tombol: kartu Frame/Theme sendiri sudah sebuah tombol, dan
   tombol di dalam tombol adalah HTML tidak sah — parser memecah nesting-nya
   sehingga tombol hapus terlempar keluar kartu. role/tabindex menjaga aksesibilitas.
   (Jangan tulis tag literal di komentar ini: pemeriksa keseimbangan tag di build.py
   ikut menghitungnya dan melaporkan MISMATCH palsu.) */
function trashBtn(onclick,label){
 return '<span class="x" role="button" tabindex="0" data-i18n-title="trash" title="'+esc(label||'')+
  '" aria-label="'+esc(label||'')+'" onclick="'+esc(onclick)+'">'+ICON_TRASH+'</span>';
}

/* ============ THEME (PRESET) LIBRARY ============ */
function themeThumb(t){
 const f=_frames.find(x=>x.id===t.frame_id);
 const url=f&&f.thumbnail_url?f.thumbnail_url:'';
 return '<span class="th"'+(url?(' style="background-image:url(\''+url+'\')"'):'')+'>' +
  '<span class="center-overlay">' +
  '<b>'+t.name+'</b>' +
  '<small>'+t.ratio+' · '+t.canvas+(t.words_per_line?(' · '+t.words_per_line+'w'):'')+'</small>' +
  '</span></span>';
}

function renderThemes(){
 const box=$('themeGrid'); if(!box)return;
 if(!_themes.length){box.innerHTML='<div class="empty">'+L('noTheme')+'</div>';return}
 box.innerHTML=_themes.map(t=>'<button class="card'+(t.id===_activeTheme?' on':'')+
  '" onclick="useTheme(\''+t.id+'\')">' +
  trashBtn("event.stopPropagation();delTheme('"+t.id+"')",L('trash')) +
  themeThumb(t) +
  '</button>').join('');
}

function loadThemes(){
 if(!(B&&B.list_presets)){renderThemes();return}
 B.list_presets(js=>{let d=[];try{d=JSON.parse(js)}catch(e){}
  _themes=Array.isArray(d)?d:[];renderThemes()});
}

function saveTheme(){
 if(!(B&&B.save_preset_as)){toast(L('guiOnly'));return}
 const def=(_themes.find(t=>t.id===_activeTheme)||{}).name||'';
 const done=js=>{let r={};try{r=JSON.parse(js)}catch(e){}
  if(r.error){toast(L('failed')+r.error);return}
  _activeTheme=r.id||'';loadThemes();toast(L('themeSaved')+(r.name||''))};
 const go=name=>{if(!name)return;
  B.save_preset_as(JSON.stringify(buildPreset()),name,'',js=>{
   let r={};try{r=JSON.parse(js)}catch(e){}
   if(r.exists){
    const ask=L('askOverwrite').replace('%s',r.exists_name||name);
    const ow=()=>B.overwrite_theme(JSON.stringify(buildPreset()),name,r.exists,done);
    if(B.confirm)B.confirm(ask,ok=>{if(ok)ow();else askName(name)});
    else if(confirm(ask))ow(); else askName(name);
    return}
   done(js)})};
 const askName=def2=>{
  if(B.prompt_text)B.prompt_text(L('themeName'),def2||'',js=>{let r={};try{r=JSON.parse(js)}catch(e){}
    if(r.ok)go((r.text||'').trim())});
  else go((prompt(L('themeName'),def2||'')||'').trim())};
 askName(def);
}

function useTheme(id){
 if(!(B&&B.load_theme))return;
 B.load_theme(id,js=>{let r={};try{r=JSON.parse(js)}catch(e){}
  if(r.error){toast(L('failed')+r.error);return}
  _activeTheme=r.id||id;applyPreset(r.preset);renderThemes();
  const t=_themes.find(x=>x.id===_activeTheme);toast(L('themeLoaded')+(t?t.name:id))});
}

function delTheme(id){
 const t=_themes.find(x=>x.id===id),nm=t?t.name:id;
 const go=()=>B.delete_theme(id,js=>{let r={};try{r=JSON.parse(js)}catch(e){}
  if(r.error){toast(L('failed')+r.error);return}
  if(_activeTheme===id)_activeTheme='';loadThemes();toast(L('themeDeleted')+nm)});
 if(!(B&&B.delete_theme)){toast(L('guiOnly'));return}
 B.confirm?B.confirm(L('askDelTheme')+'\n\n'+nm,ok=>{if(ok)go()}):(confirm(L('askDelTheme'))&&go());
}

/* ============ FONT LIBRARY ============ */
function injectFaces(){
 let el=$('userfonts');
 if(!el){el=document.createElement('style');el.id='userfonts';document.head.appendChild(el)}
 el.textContent=_fonts.filter(f=>f.url).map(f=>
  "@font-face{font-family:'"+f.css_family+"';src:url('"+f.url+"');font-display:block}").join('');
}

function renderFontList(){
 const box=$('fontList'); if(!box)return;
 const c=$('fontCount'); if(c)c.textContent=_fonts.length+L('fontCount');
 if(!_fonts.length){box.innerHTML='<div class="empty">—</div>';return}
 box.innerHTML=_fonts.map(f=>'<div class="frow">' +
  '<span class="n" style="font-family:\''+f.css_family+'\',sans-serif">'+f.family+'</span>' +
  '<span class="kb">'+f.size_kb+'K</span>' +
  (f.protected?'<span class="lock">'+L('builtin')+'</span>'
             :trashBtn("delFont('"+f.file+"')",L('trash')))+'</div>').join('');
}

function loadFonts(notify){
 if(!(B&&B.list_fonts)){renderFontList();return}
 B.list_fonts(js=>{let d=[];try{d=JSON.parse(js)}catch(e){}
  if(!Array.isArray(d)){toast(L('failed')+((d&&d.error)||'?'));return}
  _fonts=d;injectFaces();
  const has=f=>_fonts.some(x=>x.file===f);
  if(!has(S.sub.font)&&_fonts[0])S.sub.font=_fonts[0].file;
  if(!has(S.head.font)&&_fonts[0])S.head.font=_fonts[0].file;
  if(!has(S.wm.font)&&_fonts[0])S.wm.font=_fonts[0].file;
  syncAll();buildInspector();renderFontList();
  if(notify)toast(_fonts.length+L('fontCount'))});
}

function importFont(){
 if(!(B&&B.import_font_dialog)){toast(L('guiOnly'));return}
 B.import_font_dialog(js=>{let r={};try{r=JSON.parse(js)}catch(e){}
  if(r.error){toast(L('failed')+r.error);return}
  const n=(r.imported||[]).length;
  if((r.errors||[]).length)toast(L('failed')+r.errors[0]);
  else if(n)toast(n+L('fontCount'));
  if(n)loadFonts()});
}

function delFont(file){
 const f=_fonts.find(x=>x.file===file),nm=f?f.family:file;
 const go=()=>B.delete_font(file,js=>{let r={};try{r=JSON.parse(js)}catch(e){}
  if(r.error){toast(L('failed')+r.error);return}
  if(S.sub.font===file)S.sub.font='subtitle.ttf';
  if(S.head.font===file)S.head.font='title.ttf';
  if(S.wm.font===file)S.wm.font='title.ttf';
  toast(L('fontDeleted')+nm);loadFonts()});
 if(!(B&&B.delete_font)){toast(L('guiOnly'));return}
 B.confirm?B.confirm(L('askDelFont')+'\n\n'+nm,ok=>{if(ok)go()}):(confirm(L('askDelFont'))&&go());
}

function openFontsFolder(){
 if(B&&B.open_fonts_folder){B.open_fonts_folder(()=>{});toast('assets/fonts/')}
 else toast(L('guiOnly'));
}

/* ============ OVERLAY (STICKER) LIBRARY ============ */
function renderOverlayList(){
 const box=$('overlayGrid'), stat=$('overlayStatus');
 if(!box)return;
 if(stat){
  stat.textContent=S.png.name?S.png.name:L('noPng');
 }
 if(!S.png.path && !S.png.name){
  box.innerHTML='<div class="empty">'+L('noPng')+'</div>';
  return;
 }
 const imgUrl=S.png.url||'';
 const imgHtml=imgUrl?('<span class="th" style="background-image:url(\''+imgUrl+'\')">' +
  '<span class="center-overlay"><b>'+(S.png.name||'Sticker')+'</b></span></span>'):'';
 box.innerHTML='<button class="card on">' +
  trashBtn("event.stopPropagation();clearIcon()",L('trash')) +
  imgHtml + '</button>';
}

function importOverlay(){
 if(!(B&&B.import_overlay_dialog)){toast(L('guiOnly'));return}
 B.import_overlay_dialog(js=>{let r={};try{r=JSON.parse(js)}catch(e){}
  if(r.error){toast(L('failed')+r.error);return}
  if(!r.path)return;
  S.png.on=true;
  S.png.name=r.name||String(r.path).split('/').pop()||'Sticker';
  S.png.path=r.path;
  S.png.url=r.url||'';
  setOverlayImg(S.png.url);
  syncAll();buildInspector();renderOverlayList();toast(S.png.name);
 });
}

function clearIcon(){
 S.png.on=false;S.png.name='';S.png.path='';S.png.url='';
 setOverlayImg('');
 syncAll();buildInspector();renderOverlayList();
}

/* ---- Intro Cover: impor gambar latar (item 12) ----
   Memakai dialog native yang SAMA dengan stiker (`import_overlay_dialog`): file disalin
   ke assets/overlays/ dan yang disimpan di preset adalah PATH RELATIF. Kalau memakai
   <input type=file> biasa, gambar cuma ada di memori halaman (data URL) — preview
   terlihat benar tapi render tidak menemukan filenya, kelas bug yang sudah pernah
   kejadian dengan stiker. */
function importIntroBg(){
 if(!(B&&B.import_overlay_dialog)){toast(L('guiOnly'));return}
 B.import_overlay_dialog(js=>{let r={};try{r=JSON.parse(js)}catch(e){}
  if(r.error){toast(L('failed')+r.error);return}
  if(!r.path)return;
  S.intro.bg=r.path;
  S.intro.bgUrl=r.url||'';
  S.intro.on=true;
  syncAll();buildInspector();
  toast(r.name||String(r.path).split('/').pop());
 });
}
function clearIntroBg(){
 S.intro.bg='';S.intro.bgUrl='';
 syncAll();buildInspector();
}

/* ============ ACCORDION HANDLER FOR LIBRARY ============
   Panel Library memakai layout FIXED (tanpa scroll induk), jadi kartu yang TERBUKA
   mendapat sisa ruang. Kalau semua kartu ditutup panel jadi kosong dan bingung, dan
   kalau semua dibuka tiap seksi cuma dapat sisa sempit. Karena itu: satu kartu terbuka
   pada satu waktu (accordion sungguhan), sama seperti panel Style di kanan. */
function toggleLibAcc(id){
 const el=$(id);
 if(!el)return;
 const willOpen=!el.classList.contains('on');
 document.querySelectorAll('#libraryScroll > .acc').forEach(a=>a.classList.remove('on'));
 if(willOpen)el.classList.add('on');
}

/* ============ THUMBNAIL SIZE CONTROLLER ============ */
let _thumbSize='normal';

function setThumbSize(sz){
 _thumbSize=sz;
 $('bThumbSmall').classList.toggle('on',sz==='small');
 $('bThumbNorm').classList.toggle('on',sz==='normal');
 const grids=document.querySelectorAll('.cards');
 grids.forEach(g=>{
  g.classList.toggle('thumb-small',sz==='small');
  g.classList.toggle('thumb-norm',sz==='normal');
 });
}

/* ============ ZOOM GESTURE: ctrl+wheel / pinch -> HANYA kanvas preview ============
   bug.txt P1.5. Kenapa harus di halaman dan bukan cuma di filter Qt: hanya listener
   `wheel` NON-PASSIVE di dalam halaman yang boleh memanggil preventDefault() untuk
   membatalkan zoom bawaan Chromium. Filter Qt (NoZoomFilter) tetap dipertahankan
   sebagai jaring untuk ctrl+plus/minus/0.
   Di dalam area preview: gestur me-zoom preview. Di luar: gestur DIBATALKAN saja
   (tidak nge-zoom apa pun) — bukan dibiarkan nge-zoom seluruh UI. */
function initZoomGesture(){
 if(window.__zoomGesture)return;
 window.__zoomGesture=true;
 const onWheel=e=>{
  if(!e.ctrlKey)return;              // wheel biasa = scroll normal, jangan diganggu
  e.preventDefault();                // apa pun posisinya: JANGAN zoom halaman
  const vp=$('previewViewport');
  if(!vp)return;
  const r=vp.getBoundingClientRect();
  const inPreview=(e.clientX>=r.left&&e.clientX<=r.right&&
                   e.clientY>=r.top&&e.clientY<=r.bottom);
  if(!inPreview)return;              // di luar preview: cukup dibatalkan
  // deltaY < 0 = gulir ke atas / pinch keluar = perbesar
  setZoom(S.zoom+(e.deltaY<0?10:-10));
 };
 // passive:false WAJIB, kalau tidak preventDefault() diabaikan browser.
 window.addEventListener('wheel',onWheel,{passive:false});
 document.addEventListener('wheel',onWheel,{passive:false});
}

/* ============ RESIZER DRAG HANDLER ============ */
function initResizer(){
 const resizer=$('resizerLeft');
 if(!resizer)return;
 let isDragging=false, startX=0, startW=240;

 resizer.addEventListener('mousedown',e=>{
  isDragging=true;
  startX=e.clientX;
  const col=$('colLeft');
  startW=col?col.getBoundingClientRect().width:240;
  resizer.classList.add('dragging');
  document.body.style.cursor='col-resize';
  document.body.style.userSelect='none';
 });

 window.addEventListener('mousemove',e=>{
  if(!isDragging)return;
  const dx=e.clientX-startX;
  const newW=Math.max(160,Math.min(480,startW+dx));
  document.documentElement.style.setProperty('--left-w',newW+'px');
 });

 window.addEventListener('mouseup',()=>{
  if(!isDragging)return;
  isDragging=false;
  resizer.classList.remove('dragging');
  document.body.style.cursor='';
  document.body.style.userSelect='';
 });
}

/* ============ RANDOM ============ */
function randomStyle(){
 const pick=a=>a[Math.floor(Math.random()*a.length)];
 S.sub.color=pick(PAL.slice(0,4));
 S.head.color=pick(PAL.slice(0,4));
 if(_fonts.length){S.sub.font=pick(_fonts).file;S.head.font=pick(_fonts).file}
 S.video.scale=+(0.6+Math.random()*0.4).toFixed(2);
 S.sub.anim=pick(['none','pop','fade','up','word','karaoke']);
 setWpl(pick([1,3,5]));
 syncAll();buildInspector();toast(L('randomized'));
}

/* ============ BRIDGE + BOOT ============ */
function initBridge(tries){
 tries=tries||0;
 if(B)return;
 if(typeof qt!=='undefined'&&qt.webChannelTransport&&typeof QWebChannel!=='undefined'&&!window.__bt){
  window.__bt=true;
  try{new QWebChannel(qt.webChannelTransport,ch=>{
   B=ch.objects.bridge;window._bridge=B;
   if(B.get_language)B.get_language(js=>{try{const d=JSON.parse(js);LANG=(d.language==='en')?'en':'id'}catch(e){}
    bootData()});
   else bootData();
  })}catch(e){window.__bt=false}
 }
 if(!B&&tries<60)setTimeout(()=>initBridge(tries+1),100);
}

function bootData(){
 initResizer();
 initZoomGesture();
 loadFrames();
 loadFonts();
 loadThemes();
 loadCanvases();
 loadActivePreset();
}

window.addEventListener('DOMContentLoaded',()=>{
 initResizer();
 initZoomGesture();
 initBridge();
 applyI18n();
});
