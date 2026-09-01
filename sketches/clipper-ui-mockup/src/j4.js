function fontOpts(){return _fonts.length?_fonts.map(f=>[f.file,f.family+(f.protected?' ('+L('builtin')+')':'')]):[['','—']]}

function buildInspector(){
 const box=$('inspector'); if(!box)return;
 let h='';

 // 1. Canvas (Format & Rasio). Tidak ada lagi label mati "1080×1920": angka itu sudah
 //    tertulis di tiap opsi dropdown, dan sebagai teks terpisah ia cuma membingungkan
 //    (bug.txt P4.16).
 h+=sec('canvas','',L('secCanvas'),
   selectBox(L('ratio'),_canvases.map(c=>[c.id,c.label+' · '+c.w+'×'+c.h]),S.canvasId,'setCanvasSize(this.value)'));

 // 2. Video — Posisi X & Y memakai slider zero-center (0 = tepat tengah kanvas).
 h+=sec('video','',L('secVideo'),
   selectBox(L('sourceRatio'),[['16/9','16:9'],['19/6','19:6'],['4/3','4:3'],['1/1','1:1'],['9/16','9:16']],S.video.aspect,'set("video.aspect",this.value);buildInspector()')+
   slider(L('scale'),scaleToZoom(S.video.scale),0,300,1,'setVideoZoom(this)','%')+
   sliderXY('video')+
   slider(L('radius'),S.video.radius,0,200,1,'setN("video.radius",this)')+
   '<div class="row"><button class="btn sm" onclick="centerV()">'+L('center')+'</button>'+
   '<button class="btn sm" onclick="resetV()">'+L('reset')+'</button></div>'+
   '<div class="divider"></div>'+
   '<div class="ctl"><label>'+L('blurBg')+'</label>'+sw(!!S.video.blurOn,'toggleB("video.blurOn")')+'</div>'+
   (S.video.blurOn?slider(L('blurRadius'),(S.video.blur||40),0,200,1,'setN("video.blur",this)'):''));

 // 3. Headline (item 22: hapus textBox, hapus label Font, hapus hint, tambah divider)
 const hd=S.head;
 h+=sec('head','',L('secHead'),
   selectBox('',fontOpts(),hd.font,'set("head.font",this.value);buildInspector()')+
   slider(L('size'),hd.size,20,240,1,'setN("head.size",this)')+
   slider(L('maxLines'),hd.maxLines,1,4,1,'setN("head.maxLines",this)')+
   sliderXY('head')+
   alignBlock('head')+
   slider(L('lineGap'),Math.round(hd.lineSpacing*100),-55,60,1,'setNr("head.lineSpacing",this,100)')+
   '<div class="divider"></div>'+
   '<div class="ctl full"><label>'+L('color')+'</label></div>'+colorBlock('head','color',hd.color)+
   strokeBlock('head')+
   outlineBlock('head')+
   shadowBlock('head'),
   sw(hd.on,'toggleB("head.on")'));

 // 4. Subtitle (item 22: hapus textBox manual, hapus label Font, hapus hints, tambah divider)
 const s=S.sub;
 h+=sec('sub','',L('secSub'),
   selectBox('',fontOpts(),s.font,'set("sub.font",this.value);buildInspector()')+
   slider(L('size'),s.size,20,240,1,'setN("sub.size",this)')+
   slider(L('maxLines'),s.maxLines,1,4,1,'setN("sub.maxLines",this)')+
   sliderXY('sub')+
   alignBlock('sub')+
   slider(L('lineGap'),Math.round(s.lineSpacing*100),-55,60,1,'setNr("sub.lineSpacing",this,100)')+
   '<div class="divider"></div>'+
   '<div class="ctl full"><label>'+L('color')+'</label></div>'+colorBlock('sub','color',s.color)+
   strokeBlock('sub')+
   outlineBlock('sub')+
   shadowBlock('sub')+
   selectBox(L('animation'),[['none',L('none')],['pop',L('pop')],['fade',L('fade')],['up',L('up')],
     ['word',L('wordAnim')],['karaoke',L('karaoke')]],s.anim,'set("sub.anim",this.value);buildInspector()')+
   ((s.anim==='word'||s.anim==='karaoke')?
     ('<div class="ctl full"><label>'+L('activeColor')+'</label></div>'+
      colorBlock('sub','active',s.active)):'')+
   selectBox(L('wordsPerLine'),[[1,L('wpl1')],[3,L('wpl3')],[5,L('wpl5')]],
     (S.sub.wpl||3),'setWpl(this.value)'));

 // 5. Creator (Watermark) — DIKEMBALIKAN (permintaan user 2026-09-01): kartu ini yang
 //    dipakai untuk mengatur TATA LETAK teks "Creator!" di kanvas. Sebelumnya ia sempat
 //    dibuang karena salah tulis di bug.txt.
 //    Bentuknya mengikuti aturan item 22 yang sama dengan Headline & Subtitle:
 //    label "Font" dan "Align" dihilangkan, tanpa .hint, dan satu divider memisahkan
 //    [Font, Size, X/Y, Align] dari [Warna, Outline, Shadow].
 //    Kotak teks manual TIDAK dipasang: teks watermark memakai penanda otomatis
 //    (WM_AUTO_TOKENS) yang saat render diganti nama kreator video.
 const w=S.wm;
 h+=sec('wm','',L('secWm'),
   selectBox('',fontOpts(),w.font,'set("wm.font",this.value);buildInspector()')+
   slider(L('size'),w.size,20,240,1,'setN("wm.size",this)')+
   sliderXY('wm')+
   alignBlock('wm')+
   '<div class="divider"></div>'+
   '<div class="ctl full"><label>'+L('color')+'</label></div>'+colorBlock('wm','color',w.color)+
   strokeBlock('wm')+
   outlineBlock('wm')+
   shadowBlock('wm'),
   sw(w.on,'toggleB("wm.on")'));

 // 6. Sticker (item 22: reorder Size->X/Y->divider->Opacity->Shadow)
 h+=sec('png','',L('secPng'),
   slider(L('size'),S.png.w,40,900,1,'setN("png.w",this)')+
   sliderXY('png')+
   '<div class="divider"></div>'+
   slider(L('opacity'),Math.round(S.png.opacity*100),0,100,1,'setNr("png.opacity",this,100)','%')+
   shadowBlock('png'),
   sw(S.png.on,'toggleB("png.on")'));

 // 7. Intro Cover (item 12) — lapisan penutup di detik-detik AWAL video.
 //    Video & audio utama TETAP jalan dari detik 0 di latar; cover hanya menutupi
 //    layar lalu fade out. Gunanya: frame pertama itulah yang dipakai TikTok/Shorts
 //    sebagai thumbnail feed.
 //    Kontrol hanya muncul saat sakelarnya ON supaya panel tidak penuh saat tidak dipakai.
 h+=sec('intro','',L('secIntro'),
   (S.intro.on?(
     slider(L('introDur'),(+S.intro.dur||0.4).toFixed(2),0.1,2,0.05,'setNf("intro.dur",this)','s')+
     slider(L('introFade'),(+S.intro.fade||0).toFixed(2),0,1,0.05,'setNf("intro.fade",this)','s')+
     '<div class="divider"></div>'+
     '<div class="ctl full"><label>'+L('introBg')+'</label>'+
     '<div class="row"><button class="btn sm" onclick="importIntroBg()">＋ '+L('import')+'</button>'+
     (S.intro.bg?('<button class="btn sm" onclick="clearIntroBg()" data-i18n-title="trash" title="'+esc(L('trash'))+'">'+ICON_TRASH+'</button>'):'')+
     '</div></div>'+
     (S.intro.bgUrl?('<div class="introthumb" style="background-image:url('+S.intro.bgUrl+')"></div>'):'')+
     '<div class="ctl"><label>'+L('introHead')+'</label>'+sw(S.intro.head,'toggleB("intro.head")')+'</div>'+
     '<div class="ctl"><label>'+L('introWm')+'</label>'+sw(S.intro.wm,'toggleB("intro.wm")')+'</div>'
   ):''),
   sw(S.intro.on,'toggleB("intro.on")'));

 // 8. Export Option (item 22: hapus hint)
 h+=sec('export','',L('secExport'),
   slider(L('quality'),S.exp.crf,14,30,1,'setN("exp.crf",this)')+
   selectBox(L('speed'),[['veryfast','veryfast'],['fast','fast'],['medium','medium'],['slow','slow']],
     S.exp.preset,'set("exp.preset",this.value)'));

 box.innerHTML=h;
 refreshWmPlaceholder();
}

/* Pusatkan / reset kotak video. `centerV` memakai perhitungan tengah yang SAMA dengan
   slider zero-center supaya tombol dan slider tidak pernah berbeda pendapat. */
function centerV(){
 S.video.x=0;
 S.video.y=centerYFor('video');
 syncAll();buildInspector()}
function resetV(){
 S.video.scale=1.0;S.video.x=0;S.video.radius=0;
 S.video.y=centerYFor('video');
 syncAll();buildInspector()}
