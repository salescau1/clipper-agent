/* ============ INSPECTOR BUILDER ============ */
function accOpen(id){S.openAcc=(S.openAcc===id)?'':id;buildInspector()}
/* PENTING: handler inline dibungkus atribut ber-kutip GANDA, jadi setiap kutip ganda
   di dalam string handler HARUS di-escape. Tanpa ini `oninput="setN("video.y",...)"`
   terpotong oleh parser HTML menjadi `setN(` dan slider tidak berfungsi. */
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;')}
function sec(id,icon,title,body,sw){
 const on=S.openAcc===id;
 return '<div class="acc'+(on?' on':'')+'">'+
  '<button class="acc-h" onclick="accOpen(\''+id+'\')"><span>'+icon+' '+title+'</span>'+
  '<span class="r">'+(sw||'')+'<span class="chev">▾</span></span></button>'+
  '<div class="acc-b">'+body+'</div></div>'}
function sw(on,fn){return '<span class="sw'+(on?' on':'')+'" onclick="event.stopPropagation();'+esc(fn)+'"></span>'}
function slider(label,val,min,max,step,fn,unit){
 return '<div class="ctl"><label>'+label+'</label><span class="num">'+val+(unit||'')+'</span>'+
  '<input class="full" style="grid-column:1/-1" type="range" min="'+min+'" max="'+max+'" step="'+(step||1)+
  '" value="'+val+'" oninput="'+esc(fn)+'"></div>'}
function selectBox(label,opts,cur,fn){
 return '<div class="ctl full">'+(label?'<label>'+label+'</label>':'')+'<select class="inp" onchange="'+esc(fn)+'">'+
  opts.map(o=>'<option value="'+esc(o[0])+'"'+(String(o[0])===String(cur)?' selected':'')+'>'+o[1]+'</option>').join('')+
  '</select></div>'}
function textBox(label,val,fn,ph,id){
 return '<div class="ctl full"><label>'+label+'</label><input class="inp"'+
  (id?' id="'+esc(id)+'"':'')+' value="'+esc(val)+'"'+
  (ph?' placeholder="'+esc(ph)+'"':'')+' oninput="'+esc(fn)+'"></div>'}

/* colour block: 5 palette + native picker (Hue & Lightness slider DIBUANG — bug.txt item 22) */
function colorBlock(key,field,val){
 const dots=PAL.map(c=>'<span class="dot'+(hex(c)===hex(val)?' on':'')+'" style="background:'+c+
  '" onclick="setColor(\''+key+'\',\''+field+'\',\''+c+'\')"></span>').join('');
 return '<div class="cp">'+
  '<div class="sw5">'+dots+
   '<input class="native" type="color" value="'+hex(val)+'" oninput="setColor(\''+key+'\',\''+field+'\',this.value)">'+
   '<span class="cval">'+hex(val)+'</span></div>'+
  '</div>'}

/* warna heksadesimal sternary: pastikan format #RRGGBB */
function hex(c){
 const s=String(c||'').trim();
 if(!s)return '#000000';
 if(s[0]!=='#')return s;
 if(s.length===4)return '#'+s[1]+s[1]+s[2]+s[2]+s[3]+s[3];
 return s.length>=7?s:'#000000';
}
/* warna stroke otomatis: hitam kalau warna terang, putih kalau gelap */
function autoStroke(hexColor){
 const c=hex(hexColor);
 if(c.length<7)return '#000000';
 const r=parseInt(c.slice(1,3),16),g=parseInt(c.slice(3,5),16),b=parseInt(c.slice(5,7),16);
 const lum=(r*0.299+g*0.587+b*0.114)/255;
 return lum>0.6?'#000000':'#FFFFFF';
}
function setColor(key,field,v){S[key][field]=hex(v);syncAll();buildInspector()}
/* setHue()/setLite() DIBUANG bersama slider Hue & Lightness (item 22) — tidak ada
   pemanggil lagi. */

/* outline color: auto | custom */
/* Perataan teks: kiri / tengah / kanan — ditampilkan sebagai IKON saja (bug.txt P4.14).
   Zona sama dengan yang dipakai auto-fit (margin 7% kiri-kanan), jadi "kiri" berarti
   menempel margin kiri, bukan tepi kanvas. Slider Geser X tetap bekerja sebagai
   geseran halus dari posisi hasil perataan.
   Nama pilihan tetap ada di `title`/aria-label supaya tetap terbaca screen reader
   dan tetap ikut sakelar bahasa. */
const ALIGN_ICON={
 left:'<svg width="14" height="12" viewBox="0 0 14 12" aria-hidden="true">'+
      '<g fill="currentColor"><rect x="1" y="1" width="12" height="1.6" rx=".8"/>'+
      '<rect x="1" y="5.2" width="7" height="1.6" rx=".8"/>'+
      '<rect x="1" y="9.4" width="10" height="1.6" rx=".8"/></g></svg>',
 center:'<svg width="14" height="12" viewBox="0 0 14 12" aria-hidden="true">'+
      '<g fill="currentColor"><rect x="1" y="1" width="12" height="1.6" rx=".8"/>'+
      '<rect x="3.5" y="5.2" width="7" height="1.6" rx=".8"/>'+
      '<rect x="2" y="9.4" width="10" height="1.6" rx=".8"/></g></svg>',
 right:'<svg width="14" height="12" viewBox="0 0 14 12" aria-hidden="true">'+
      '<g fill="currentColor"><rect x="1" y="1" width="12" height="1.6" rx=".8"/>'+
      '<rect x="6" y="5.2" width="7" height="1.6" rx=".8"/>'+
      '<rect x="3" y="9.4" width="10" height="1.6" rx=".8"/></g></svg>'
};
function alignBlock(key){
 const b=S[key], cur=b.align||'center';
 const lbl={left:L('alignLeft'),center:L('alignCenter'),right:L('alignRight')};
 const btn=v=>'<button class="btn sm'+(cur===v?' pri':'')+
  '" data-i18n-title="align'+v.charAt(0).toUpperCase()+v.slice(1)+'"'+
  ' title="'+esc(lbl[v])+'" aria-label="'+esc(lbl[v])+'"'+
  ' onclick="setAlign(\''+key+'\',\''+v+'\')">'+ALIGN_ICON[v]+'</button>';
 return '<div class="ctl full">'+
  '<div class="row">'+btn('left')+btn('center')+btn('right')+'</div></div>'}
function setAlign(k,v){S[k].align=v;syncAll();buildInspector()}

/* ====== ZERO-CENTER SLIDER X & Y (bug.txt P2.10) ======
   Aturan yang diminta user: titik TENGAH slider = posisi NETRAL (Center) di kanvas,
   seragam untuk Video, Headline, Subtitle, Creator, dan Sticker.

   Cara kerjanya: preset TETAP menyimpan koordinat ABSOLUT (renderer tidak perlu tahu
   apa pun soal slider — itu yang menjaga preview == render). Slider hanya menampilkan
   SELISIH terhadap posisi tengah. Karena itu tengah harus dihitung, dan untuk teks
   tingginya baru diketahui SETELAH auto-fit memilih ukuran font — angkanya datang dari
   `_ink` (kotak tinta yang dilaporkan mesin render), bukan ditebak di JS.

   Kenapa selisih, bukan menyimpan offset di preset: kalau UI menulis offset dan
   renderer menambahkan tengah sendiri, setiap perubahan ukuran font akan MENGGESER
   teks yang sudah pas. Dengan model selisih, `y` absolut tetap diam; yang berubah
   hanya angka yang ditampilkan. */
function inkOf(key){return _ink[key]||null}
function pngAspect(){
 // Tinggi stiker = lebar × rasio gambar asli. Diambil dari <img> yang sudah dimuat;
 // kalau belum ada gambar, anggap 1:1 (tidak ada info lain yang jujur).
 const img=document.querySelector('.rc .ic img');
 if(img&&img.naturalWidth&&img.naturalHeight)return img.naturalHeight/img.naturalWidth;
 return 1;
}
/* Untuk TEKS, `y` preset adalah baris awal gambar, BUKAN tepi atas huruf: font punya
   ascender/leading di atasnya. Mesin melaporkan `dy_top` (jarak tepi tinta dari `y`)
   dan `dcx` (simpangan pusat tinta dari tengah kanvas setelah geseran x), jadi posisi
   tengah bisa dihitung tepat tanpa coba-coba. */
function centerYFor(key){
 if(key==='video'){const g=effGeom();return Math.round((CH-g.h)/2)}
 if(key==='png')return Math.round((CH-S.png.w*pngAspect())/2);
 const b=inkOf(key);
 if(!b||!b.h)return Math.round(CH/2);   // lapisan pertama belum digambar
 return Math.round((CH-b.h)/2)-Math.round(b.dy_top||0);
}
function centerXFor(key){
 if(key==='video')return 0;                                  // 0 = tepat di tengah
 if(key==='png')return Math.round((CW-S.png.w)/2);
 const b=inkOf(key);
 // teks: x = baseX() berarti nudge 0 (mengikuti align). `dcx` mengoreksi sisa
 // pembulatan/asimetri glyph supaya pusat tinta benar-benar di tengah kanvas.
 return baseX()-Math.round((b&&b.dcx)||0);
}
function offY(key){return Math.round((num(S[key].y,0))-centerYFor(key))}
function offX(key){
 const cur=(key==='video')?num(S.video.x,0):num(S[key].x,centerXFor(key));
 return Math.round(cur-centerXFor(key));
}
function setOffY(key,el){
 const v=num(el&&el.value!==undefined?el.value:el,0);
 S[key].y=centerYFor(key)+Math.round(v);
 showNum(el,Math.round(v));
 syncAll()}
function setOffX(key,el){
 const v=num(el&&el.value!==undefined?el.value:el,0);
 S[key].x=centerXFor(key)+Math.round(v);
 showNum(el,Math.round(v));
 syncAll()}
function showNum(el,v){
 const box=el&&el.closest?el.closest('.ctl'):null;
 const n=box?box.querySelector('.num'):null;
 if(n)n.textContent=v}
/* Slider simetris: min = -max, jadi titik tengahnya PASTI 0.
   Item 22: format side-by-side X & Y dalam 1 baris + input angka manual.
   Memakai class `.ctl-xy` yang stylenya sudah ada di p3.css (bukan style inline). */
function xyRow(label,key,val,mx,setter){
 return '<div class="ctl-xy">'+
  '<span class="xy-label">'+label+'</span>'+
  '<input type="range" min="'+(-mx)+'" max="'+mx+'" step="1" value="'+val+'"'+
   ' oninput="'+esc(setter+'(\''+key+'\',this);xySync(this)')+'">'+
  '<input class="xy-num" type="number" value="'+val+'"'+
   ' onchange="'+esc(setter+'(\''+key+'\',this);xySync(this)')+'">'+
  '</div>'}
function sliderXY(key){
 return '<div class="ctl full">'+
  xyRow('X',key,offX(key),Math.round(CW/2),'setOffX')+
  xyRow('Y',key,offY(key),Math.round(CH/2),'setOffY')+
  '</div>'}

/* Sinkronkan slider <-> input angka dalam 1 baris */
function xySync(el){
 const row=el.closest('.ctl-xy'); if(!row)return;
 const rng=row.querySelector('input[type=range]'),n=row.querySelector('input[type=number]');
 if(el.type==='range'&&n)n.value=el.value;
 if(el.type==='number'&&rng)rng.value=el.value;}

/* Geser X = NUDGE dari posisi hasil perataan, bukan koordinat absolut.
   Preset tetap menyimpan `x` gaya lama (45 + nudge, diskalakan ke lebar kanvas) supaya
   preset lama terbaca; UI menampilkan nudge-nya saja agar 0 = "pas di posisi align".
   Tanpa ini slider 0..CW terasa acak: nilai 64 berarti bergeser 19px, bukan x=64. */
function baseX(){return Math.round(45*(CW/1080))}
function nudgeX(key){return Math.round((S[key].x||baseX())-baseX())}
function setNudge(key,el){const v=num(el&&el.value!==undefined?el.value:el,0);
 S[key].x=baseX()+v;
 const box=el&&el.closest?el.closest('.ctl'):null;
 const n=box?box.querySelector('.num'):null;
 if(n)n.textContent=Math.round(v);
 syncAll()}

/* Panel SHADOW lengkap. Dulu shadow hanya satu angka yang dipakai sebagai offset x=y
   dan warnanya selalu hitam (batasan ffmpeg drawtext). Setelah teks digambar
   text_engine, shadow jadi lapisan sendiri: offset x/y terpisah, warna sendiri, blur,
   dan urutan lapisan bisa ditukar.
   CATATAN PENTING untuk efek 3D: kalau warna shadow SAMA dengan warna outline,
   keduanya menyatu jadi satu massa dan kesan timbul hilang. Beri warna berbeda. */
function shadowBlock(key){
 const b=S[key];
 let h='<div class="ctl"><label>'+L('shadow')+'</label>'+sw(b.shadowOn,'toggleB("'+key+'.shadowOn")')+'</div>';
 if(!b.shadowOn)return h;
 h+=slider(L('shadowX'),b.shadowX,-40,40,1,'setN("'+key+'.shadowX",this)')+
    slider(L('shadowY'),b.shadowY,-40,40,1,'setN("'+key+'.shadowY",this)')+
    slider(L('shadowBlur'),b.shadowBlur,0,30,1,'setN("'+key+'.shadowBlur",this)')+
    '<div class="ctl full"><label>'+L('shadowColor')+'</label></div>'+
    colorBlock(key,'shadowColor',b.shadowColor)+
    '<div class="ctl full"><label>'+L('layerOrder')+'</label>'+
    '<div class="row"><button class="btn sm'+(b.layerOrder!=='shadow-fill-stroke'?' pri':'')+
    '" onclick="setOrder(\'' + key + '\',\'shadow-stroke-fill\')">'+L('orderStrokeFill')+'</button>'+
    '<button class="btn sm'+(b.layerOrder==='shadow-fill-stroke'?' pri':'')+
    '" onclick="setOrder(\'' + key + '\',\'shadow-fill-stroke\')">'+L('orderFillStroke')+'</button></div></div>';
 if(hex(b.shadowColor)===hex(b.outlineColor||autoStroke(b.color)))
  h+='<div class="warnline">'+L('shadowSameWarn')+'</div>';
 return h}
function setOrder(k,v){S[k].layerOrder=v;syncAll();buildInspector()}

function outlineBlock(key){
 const b=S[key],isAuto=!b.outlineColor;
 return '<div class="ctl full"><label>'+L('outlineColor')+'</label>'+
  '<div class="row"><button class="btn sm'+(isAuto?' pri':'')+'" onclick="setOutlineAuto(\''+key+'\')">'+L('auto')+'</button>'+
  '<button class="btn sm'+(isAuto?'':' pri')+'" onclick="setOutlineCustom(\''+key+'\')">'+L('custom')+'</button></div></div>'+
  /* Mode Auto: warna hasil hitungan ditampilkan sebagai BULATAN, bukan teks keterangan
     (item 22 membuang seluruh .hint dari panel Style). Bulatannya mati (tanpa onclick)
     karena nilainya dihitung dari warna isi teks, bukan dipilih user. */
  (isAuto?'<div class="cp"><div class="sw5"><span class="dot on" style="background:'+
    autoStroke(b.color)+'"></span><span class="cval">'+autoStroke(b.color)+'</span></div></div>'
   :colorBlock(key,'outlineColor',b.outlineColor))}
function setOutlineAuto(k){S[k].outlineColor='';syncAll();buildInspector()}
function setOutlineCustom(k){if(!S[k].outlineColor)S[k].outlineColor=autoStroke(S[k].color);syncAll();buildInspector()}

/* outline: slider bipolar. Tengah (0) = tanpa stroke.
   Ke KANAN = inner (mengikis ke dalam), ke KIRI = outer (melebar ke luar).
   State disimpan sebagai `outline` (ketebalan >=0) + `outlineMode` ('outer'|'inner');
   nilai slider = +tebal untuk inner, -tebal untuk outer. */
function strokeSliderVal(b){return (b.outlineMode==='inner'?1:-1)*Math.abs(b.outline||0)}
function setStroke(key,el){
 const v=Math.round(num(el&&el.value!==undefined?el.value:el,0));
 const b=S[key];
 b.outline=Math.abs(v);
 if(v>0)b.outlineMode='inner'; else if(v<0)b.outlineMode='outer';
 syncAll();
 const box=el&&el.closest?el.closest('.strokeWrap'):null;
 const n=box?box.querySelector('.num'):null;
 if(n)n.textContent=strokeLabel(b);
}
function strokeLabel(b){
 const w=Math.abs(b.outline||0);
 if(!w)return L('strokeOff');
 return (b.outlineMode==='inner'?'IN ':'OUT ')+w}
function strokeBlock(key){
 const b=S[key],v=strokeSliderVal(b);
 return '<div class="strokeWrap">'+
  '<div class="ctl"><label>'+L('outline')+'</label><span class="num">'+strokeLabel(b)+'</span>'+
  '<input style="grid-column:1/-1" type="range" min="-20" max="20" step="1" value="'+v+
  '" oninput="'+esc('setStroke(\''+key+'\',this)')+'"></div>'+
  '<div class="strokeEnds"><span>← '+L('outer')+'</span><span>'+L('off')+'</span><span>'+L('inner')+' →</span></div>'+
  '</div>'}

function set(path,v){const p=path.split('.');let o=S;for(let i=0;i<p.length-1;i++)o=o[p[i]];
 o[p[p.length-1]]=v;syncAll()}

/* ====== KERAPATAN SUBTITLE (1 / 3 / 5 kata) ======
   Dibakukan di theme (permintaan user 2026-08-30): SRT selalu ditulis 1 kata per entri
   oleh Stage 4, lalu theme yang menentukan tampilannya — jadi tidak perlu lagi opsi
   subtitle di tab Run, dan mengubahnya TIDAK butuh menjalankan Stage 4 ulang.

   Teks contoh dibuat otomatis sebanyak N kata supaya kerapatannya KELIHATAN di preview
   ("SUBTITLE" vs "SUBTITLE SUBTITLE SUBTITLE"). Begitu user mengetik teksnya sendiri,
   contoh otomatis berhenti menimpanya — kalau tidak, ketikan user akan hilang setiap
   pilihan kata diubah. */
function sampleSubText(n){
 return new Array(Math.max(1,+n||1)).fill('SUBTITLE').join(' ')}
function setWpl(v){
 S.sub.wpl=Math.max(1,+v||1);
 if(S.sub.autoText!==false)S.sub.text=sampleSubText(S.sub.wpl);
 syncAll();buildInspector()}
function setSubText(v){
 S.sub.text=v;
 // Kosong = kembali ke contoh otomatis; ada isi = milik user, jangan ditimpa.
 S.sub.autoText=!String(v||'').trim();
 if(S.sub.autoText)S.sub.text=sampleSubText(S.sub.wpl);
 syncAll()}
/* el = elemen input (dikirim sebagai `this`), bukan window.event — lebih andal. */
function setN(path,el){const v=num(el&&el.value!==undefined?el.value:el,0);
 set(path,v);
 const box=el&&el.closest?el.closest('.ctl'):null;
 const n=box?box.querySelector('.num'):null;
 if(n)n.textContent=Math.round(v)}
/* Sama dengan setN tapi TIDAK dibulatkan ke integer: untuk nilai pecahan seperti
   durasi intro (0.4s) yang kalau dibulatkan akan berubah jadi 0 atau 1. */
function setNf(path,el){const v=num(el&&el.value!==undefined?el.value:el,0);
 set(path,v);
 const box=el&&el.closest?el.closest('.ctl'):null;
 const n=box?box.querySelector('.num'):null;
 if(n)n.textContent=v.toFixed(2)+'s'}
function setNr(path,el,div){const raw=num(el&&el.value!==undefined?el.value:el,0);
 set(path,raw/(div||1));
 const box=el&&el.closest?el.closest('.ctl'):null;
 const n=box?box.querySelector('.num'):null;
 if(n)n.textContent=raw+'%'}
function toggleB(path){const p=path.split('.');let o=S;for(let i=0;i<p.length-1;i++)o=o[p[i]];
 const k=p[p.length-1];o[k]=!o[k];syncAll();buildInspector()}
