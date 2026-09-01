/* ============ STATE ============ */
const PAL=['#FFFFFF','#FACC15','#72E8FF','#FF6B6B','#0B1220']; // 5 warna dasar
const RC_MAX_W=250, RC_MAX_H=444;   // kotak preview maksimum (px)
let CW=1080, CH=1920;               // canvas render
let SX=1,SY=1;                      // preview px -> canvas px
let RCW=250,RCH=444;

const S={                            // state UI (mirror preset)
 canvasId:'9x16',
 frame:'',
 video:{scale:1.0,x:0,y:415,radius:0,aspect:'16/9',blurOn:false,blur:40},
 sub:{font:'subtitle.ttf',size:95,y:1686,outline:2,outlineMode:'outer',outlineColor:'',
      shadowOn:true,shadowX:3,shadowY:3,shadowColor:'#000000',shadowBlur:0,
      layerOrder:'shadow-stroke-fill',align:'center',maxLines:2,lineSpacing:-0.15,
      color:'#FFFFFF',active:'#FFA500',anim:'none',
      // Kerapatan subtitle dibakukan di theme: 1 / 3 / 5 kata. Teks contoh dibuat
      // sebanyak itu supaya kerapatannya kelihatan langsung di preview.
      wpl:3,autoText:true,text:'SUBTITLE SUBTITLE SUBTITLE'},
 head:{on:true,text:'HEADLINE',font:'title.ttf',size:69,x:45,y:69,lineSpacing:-0.25,maxLines:2,align:'center',
       outline:6,outlineMode:'outer',outlineColor:'',
       shadowOn:true,shadowX:8,shadowY:8,shadowColor:'#000000',shadowBlur:0,
       layerOrder:'shadow-stroke-fill',color:'#FFFFFF'},
 wm:{on:true,text:'Creator!',font:'title.ttf',size:130,x:751,y:225,align:'center',outline:7,outlineMode:'outer',outlineColor:'',
     shadowOn:true,shadowX:6,shadowY:6,shadowColor:'#000000',shadowBlur:0,
     layerOrder:'shadow-stroke-fill',color:'#D94B0A'},
 png:{on:false,name:'',path:'',x:69,y:363,w:276,opacity:1,
    shadowOn:false,shadowX:0,shadowY:0,shadowBlur:0,shadowColor:'#000000',layer_order:'shadow-stroke-fill'},
 // Intro Cover (item 12). Lapisan penutup di detik-detik awal video untuk thumbnail
 // feed TikTok/Shorts. Video & audio utama tetap jalan dari detik 0 di latar.
 intro:{on:false,dur:0.4,fade:0.15,bg:'',bgUrl:'',head:true,wm:true},
 exp:{crf:18,preset:'medium'},
 view:'adjust',safe:true,zoom:100,openAcc:'video'
};
let _frames=[],_fonts=[],_themes=[],_canvases=[],_activeTheme='';
/* Kotak tinta tiap lapisan teks (dari mesin render, lewat bridge). Dipakai slider
   zero-center: "tengah" hanya bisa dihitung kalau tinggi blok teks SETELAH auto-fit
   diketahui, dan angka itu hanya ada di sisi Python. */
let _ink={};
/* `_booting` true selama halaman memuat preset aktif dari disk. Tanpa penjaga ini
   auto-apply akan langsung menulis balik preset yang baru saja dibaca (dan menimpa
   field yang belum sempat diterapkan ke state UI). */
let _booting=true;

/* ============ CANVAS SIZE ============ */
function computeRC(){
 const r=CW/CH;
 if(r>=RC_MAX_W/RC_MAX_H){RCW=RC_MAX_W;RCH=Math.round(RC_MAX_W/r)}
 else{RCH=RC_MAX_H;RCW=Math.round(RC_MAX_H*r)}
 SX=CW/RCW; SY=CH/RCH;
 document.documentElement.style.setProperty('--rcw',RCW+'px');
 document.documentElement.style.setProperty('--rch',RCH+'px');
}
function setCanvasSize(id){
 const c=_canvases.find(x=>x.id===id); if(!c)return;
 const ow=CW,oh=CH; CW=c.w; CH=c.h; S.canvasId=id;
 const sx=CW/ow, sy=CH/oh, ss=Math.min(sx,sy), R=Math.round;
 // skalakan semua koordinat supaya tidak keluar frame saat rasio berubah
 S.video.y=R(S.video.y*sy); S.video.x=R((+S.video.x||0)*sx);
 S.video.radius=R(S.video.radius*ss);
 ['sub','head','wm'].forEach(k=>{const b=S[k];
  if('x' in b)b.x=R(b.x*sx); if('y' in b)b.y=R(b.y*sy);
  b.size=R(b.size*ss); b.outline=R(b.outline*ss);
  // shadow adalah offset x/y terpisah (bukan lagi satu angka). Dulu baris ini
  // menulis b.shadow=NaN untuk head/wm yang tidak punya field itu.
  if('shadowX' in b)b.shadowX=R(b.shadowX*ss);
  if('shadowY' in b)b.shadowY=R(b.shadowY*ss);
  if('shadowBlur' in b)b.shadowBlur=R(b.shadowBlur*ss)});
 S.png.x=R(S.png.x*sx); S.png.y=R(S.png.y*sy); S.png.w=R(S.png.w*ss);
 computeRC(); syncAll(); buildInspector();
}

function V(k,v){document.documentElement.style.setProperty(k,v)}
/* CATATAN: helper CSS untuk teks (cssFam / shadowCss / strokeCss) sudah DIBUANG.
   Tidak ada lagi teks yang digambar CSS di preview — subtitle, headline, dan
   watermark semuanya lapisan PNG dari stages/text_engine.py. Membiarkan helper itu
   hidup berarti mengundang orang menggambar teks dengan mesin kedua lagi. */

/* Geometri video efektif. Sejak 2026-08-30 preview TIDAK lagi meniru
   cover_frame_window(): pemaksaan itu dibuang dari renderer juga, karena ia menimpa
   nilai skala pilihan user (bug yang dilaporkan user: slider terasa tidak berpengaruh).
   Latar tetap tidak bocor hitam karena base kanvas = video yang di-cover penuh. */
function effGeom(){
 const v=S.video;
 let r=16/9; try{const p=String(v.aspect).split('/');r=(+p[0])/(+p[1])}catch(e){}
 const w=Math.round(CW*v.scale);
 return {w:w,h:Math.round(w/r),y:Math.round(v.y),x:Math.round(+v.x||0)};
}

/* ====== SKALA VIDEO: 0% = utuh (tanpa terpotong), 300% = penuh kanvas ======
   Preset tetap menyimpan `video.scale` ABSOLUT (fraksi lebar kanvas) supaya renderer
   tidak perlu tahu apa pun soal slider — itu yang menjamin preview == render. Slider
   hanya lapisan tampilan di atas nilai itu.
     z=0   -> scale 1.0  : lebar video = lebar kanvas, seluruh frame video terlihat
     z=300 -> scale cover: tinggi video = tinggi kanvas, kanvas terisi penuh */
function coverScale(){
 let r=16/9; try{const p=String(S.video.aspect).split('/');r=(+p[0])/(+p[1])}catch(e){}
 return Math.max(1.0001,(CH*r)/CW);
}
function zoomToScale(z){const c=coverScale();
 return 1+(c-1)*(Math.max(0,Math.min(300,+z||0))/300)}
function scaleToZoom(s){const c=coverScale();
 return Math.round(Math.max(0,Math.min(300,((+s||1)-1)/(c-1)*300)))}
function setVideoZoom(el){
 const z=num(el&&el.value!==undefined?el.value:el,0);
 S.video.scale=+zoomToScale(z).toFixed(4);
 const box=el&&el.closest?el.closest('.ctl'):null;
 const n=box?box.querySelector('.num'):null;
 if(n)n.textContent=Math.round(z)+'%';
 syncAll()}

function syncAll(){
 const v=S.video;
 const g=effGeom();
 V('--vw',Math.round(g.w/SX)+'px');
 V('--vy',Math.round(g.y/SY)+'px');
 V('--vx',Math.round((g.x||0)/SX)+'px');
 V('--vr',Math.round(v.radius/SX)+'px');
 V('--vratio',v.aspect);
 /* Blur background: kelasnya di kotak preview (.rc), bukan di .vid — lapisan blur
    adalah LATAR di belakang video, sama seperti di renderer. Radius diskalakan
    canvas px -> preview px lewat SX supaya kuatnya sama dengan hasil render. */
 V('--blurpx',(Math.max(0,+v.blur||0)/SX).toFixed(2)+'px');
 document.querySelectorAll('.rc').forEach(e=>e.classList.toggle('blur-bg',!!v.blurOn));
 V('--icx',Math.round(S.png.x/SX)+'px');
 V('--icy',Math.round(S.png.y/SY)+'px');
 V('--icsize',Math.round(S.png.w/SX)+'px');
 V('--icop',(+S.png.opacity).toFixed(3));
 document.querySelectorAll('.rc .ic').forEach(e=>e.classList.toggle('empty',!S.png.on));
 requestTextLayers();
 // Tombol "Terapkan" sudah dibuang: preset aktif ditulis otomatis (debounce) supaya
 // tab Run selalu memakai gaya yang sedang dilihat user. `_booting` mencegah
 // penulisan balik saat preset baru saja DIMUAT dari disk.
 if(!_booting)scheduleAutoApply();
}

/* ====== AUTOSAVE DRAF PRESET (debounce 600ms) ======
   Fungsi ini pernah HILANG dari mockup (dibuang tanpa sengaja saat perombakan UI).
   Akibatnya `syncAll()` melempar ReferenceError di baris terakhirnya, sehingga SEMUA
   kode yang dipanggil sesudah syncAll() di dalam handler yang sama tidak pernah jalan —
   `buildInspector()` di toggleB/setColor/setAlign tidak dieksekusi, jadi sakelar ON/OFF
   dan tombol pilihan tampak "tidak merespons" walau state-nya sudah berubah. Satu
   fungsi hilang = beberapa laporan bug sekaligus.

   ATURAN: autosave TIDAK boleh memicu efek tingkat aplikasi (mis. pindah tab). Ia
   dijalankan puluhan kali per menit saat slider digeser. */
let _apTimer=null;
function scheduleAutoApply(){
 if(!(B&&B.save_preset))return;
 const st=$('applyState'); if(st)st.textContent=L('saving');
 if(_apTimer)clearTimeout(_apTimer);
 _apTimer=setTimeout(()=>{
  _apTimer=null;
  try{B.save_preset(JSON.stringify(buildPreset()))}
  catch(e){if(st)st.textContent=L('failed')+e;return}
  if(st)st.textContent=L('saved');
 },600);
}

/* ====== LAPISAN TEKS: digambar stages/text_engine.py (mesin yang sama dgn render) ======
   Preview TIDAK menggambar teks apa pun dengan CSS — subtitle, headline, dan watermark
   semuanya PNG dari mesin render. Alasannya: CSS dan mesin render tidak pernah bisa
   sama (CSS tak punya auto-fit, urutan lapisan lewat paint-order, pengukur lebar teks
   beda, dan libass menskalakan outline relatif PlayRes).
   Permintaan di-debounce supaya menggeser slider tidak membanjiri bridge. */
let _tlTimer=null, _tlPending=false, _tlBusy=false, _tlLast='';
function requestTextLayers(){
 if(!(B&&B.render_text_layers))return;
 if(_tlTimer)clearTimeout(_tlTimer);
 _tlTimer=setTimeout(doTextLayers,60);
}
/* Jumlah lapisan subtitle yang perlu digambar: mode per-kata butuh satu lapisan
   per kata aktif supaya animasinya bisa diputar seperti di MP4. */
function subFrameCount(){
 const a=S.sub.anim;
 if(a!=='word'&&a!=='karaoke')return 1;
 let w=String(S.sub.text||'').trim().split(/\s+/).filter(Boolean);
 const wpl=S.sub.wpl|0; if(wpl>0)w=w.slice(0,wpl);
 return Math.max(1,w.length);
}
// Nama creator untuk contoh watermark. Kotak watermark memuat PENANDA (mis. "Creator!")
// yang saat render diganti nama creator video yang diproses. Preview menggantinya dengan
// creator video yang SEDANG DIPILIH di panel Review, jadi preview == hasil.
// Daftar penanda ini WAJIB sama dengan AUTO_WATERMARK_TOKENS di stages/stage5_final.py —
// kalau berbeda, preview dan render akan menampilkan teks yang berbeda.
const WM_AUTO_TOKENS=['creator!','creator','nama creator','nama kreator',
                      'kreator!','kreator','<creator>','{creator}'];
let _creatorHint='';
function loadCreatorHint(){
 if(!B||!B.creator_hint)return;
 B.creator_hint(v=>{_creatorHint=String(v||''); refreshWmPlaceholder(); requestTextLayers();});
 // Ikuti perubahan: user memilih video lain di Review -> contoh watermark ikut berubah.
 // Tanpa ini preview tetap memperlihatkan nama channel sebelumnya (bug 2026-08-30).
 if(B.creator_hint_changed&&B.creator_hint_changed.connect)
  B.creator_hint_changed.connect(v=>{
   _creatorHint=String(v||''); refreshWmPlaceholder(); requestTextLayers();});
}
/* Nama creator dari host. Dulu ada teks keterangan di bawah kotak teks watermark;
   kotak teks + keterangan itu sudah dibuang di panel Style (item 22), jadi yang
   tersisa hanyalah menggambar ulang lapisan teks supaya preview memakai nama kreator
   video yang sedang dipilih di panel Review. */
function refreshWmPlaceholder(){/* tidak ada lagi elemen keterangan di panel Style */}
function wmIsAuto(){
 return WM_AUTO_TOKENS.indexOf(String(S.wm.text||'').trim().toLowerCase())>=0;
}
function wmEffectiveText(){
 const t=String(S.wm.text||'').trim();
 if(!t||wmIsAuto())return _creatorHint||'CREATOR';  // penanda -> nama creator video terpilih
 return t;                                 // teks lain dipakai harfiah
}
function textLayerSpec(){
 const p=buildPreset();
 return JSON.stringify({canvas:{w:CW,h:CH},
  blocks:{sub:Object.assign({},p.subtitle,{text:S.sub.text,enabled:true,
           _frames:subFrameCount()}),
          wm:Object.assign({},p.watermark,{text:wmEffectiveText()}),
          head:Object.assign({},p.headline,{text:S.head.text})}});
}
function doTextLayers(){
 const spec=textLayerSpec();
 if(spec===_tlLast&&!_tlPending)return;
 if(_tlBusy){_tlPending=true;return}
 _tlBusy=true; _tlLast=spec;
 B.render_text_layers(spec,js=>{
  _tlBusy=false;
  let d={};try{d=JSON.parse(js)}catch(e){}
  if(d.error){console.warn('text layer:',d.error)}
  else{
   applyTextLayer('headlayer',d.head);
   applyTextLayer('wmlayer',d.wm);
   applySubLayers(d.sub);
   showFitInfo(d);
   /* Simpan kotak tinta tiap blok: dipakai slider zero-center untuk tahu di mana
      "tengah" sebenarnya (tinggi blok baru diketahui setelah auto-fit). */
   ['head','wm','sub'].forEach(k=>{if(d[k]&&d[k].ink)_ink[k]=d[k].ink});
  }
  if(_tlPending){_tlPending=false;doTextLayers()}
 });
}
function applyTextLayer(cls,info){
 const url=(info&&info.url)||'';
 document.querySelectorAll('.rc .'+cls).forEach(el=>{
  if(url){if(el.getAttribute('src')!==url)el.setAttribute('src',url);el.style.display=''}
  else{el.removeAttribute('src');el.style.display='none'}});
}
/* Putar deretan lapisan subtitle. Tiap lapisan adalah gambar yang BENAR-BENAR muncul
   di MP4 pada momen itu, jadi ini bukan animasi hias — ia memperlihatkan kata aktif
   dengan warna & ukuran hasil render. */
let _subTimer=null;
function applySubLayers(info){
 if(_subTimer){clearInterval(_subTimer);_subTimer=null}
 const urls=(info&&info.urls&&info.urls.length)?info.urls:((info&&info.url)?[info.url]:[]);
 if(!urls.length){applyTextLayer('sublayer',null);return}
 let i=0;
 const show=()=>{document.querySelectorAll('.rc .sublayer').forEach(el=>{
  if(el.getAttribute('src')!==urls[i])el.setAttribute('src',urls[i]);el.style.display=''});
  i=(i+1)%urls.length};
 show();
 if(urls.length>1)_subTimer=setInterval(show,430);
}
/* Ukuran font hasil auto-fit. Keterangan `.hint` di panel Style sudah dibuang (item 22),
   jadi tidak ada lagi elemen headFit/wmFit/subFit untuk diisi. Ukuran yang benar-benar
   dipakai tetap terlihat langsung di lapisan teks preview (digambar mesin render yang
   sama dengan MP4), jadi informasinya tidak hilang — hanya tidak lagi berupa teks. */
function showFitInfo(d){/* tidak ada elemen keterangan auto-fit di panel Style */}

/* ============ VIEW + ZOOM ============ */
function setView(mode){S.view=mode;
 $('rcA').style.display=mode==='adjust'?'':'none';
 $('rcB').style.display=mode==='output'?'':'none';
 $('tabAdj').classList.toggle('on',mode==='adjust');
 $('tabOut').classList.toggle('on',mode==='output');
 updateViewLabel();syncAll()}
function updateViewLabel(){const e=$('viewLabel');if(!e)return;
 const ratio=_canvases.find(c=>c.id===S.canvasId);
 const rt=ratio?ratio.ratio:'';
 e.textContent=S.view==='output'?(L('output916')+' '+rt):L('inputAdjustment');
 e.classList.toggle('out',S.view==='output')}
function setZoom(v){S.zoom=clamp(Math.round(num(v,100)),40,250);
 V('--zoom',(S.zoom/100).toFixed(3));
 const r=$('zoomRange');if(r)r.value=S.zoom;
 const t=$('zoomVal');if(t)t.textContent=S.zoom+'%'}
function zoomStep(d){setZoom(S.zoom+d*10)}
function toggleSafe(){S.safe=!S.safe;$('safeSw').classList.toggle('on',S.safe);
 document.querySelectorAll('.rc .safe').forEach(e=>e.classList.toggle('on',S.safe))}
