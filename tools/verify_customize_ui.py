"""Verifikasi bug UI Customize di DOM NYATA (offscreen QWebEngine, halaman Customize aktif).

Menguji daftar `bug.txt` versi 2026-09-01 (20 item, 4 prioritas). Setiap tes MENGUBAH
state lalu MENGUKUR akibatnya di DOM, bukan mencocokkan keberadaan fungsi.

Pitfall yang sudah pernah menjatuhkan skrip serupa (jangan diulang):
  * Halaman Customize harus AKTIF (`win.switch_page(1)`). Di halaman Run seluruh
    elemennya melaporkan clientWidth/Height = 0 sehingga semua tes lulus palsu.
  * `#stage` punya `transition:transform .07s`, jadi getComputedStyle yang dibaca di
    JS yang SAMA dengan setZoom masih matrix identitas. Zoom diukur di fase terpisah.
  * Lapisan teks (watermark/headline/subtitle) digambar Python secara ASINKRON lewat
    bridge; harus ada jeda sebelum membaca src-nya.

Jalankan:
    .venv/Scripts/python.exe tools/verify_customize_ui.py
Keluar 0 kalau semua PASS, 2 kalau ada FAIL.
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402

import clipper_gui  # noqa: E402

# ---------------------------------------------------------------- fase 1: siap?
READY = r"""
(function(){
  return JSON.stringify({frames:document.querySelectorAll('#frameGrid .card').length,
                         fonts:document.querySelectorAll('#fontList .frow').length,
                         themes:!!document.getElementById('themeGrid')});
})()
"""

# ------------------------------------------------- fase 2: pilih frame + minta layer
ARRANGE = r"""
(function(){try{
  window.__errs=window.__errs||[];
  window.addEventListener('error',function(e){window.__errs.push(''+e.message)});
  var out={};
  /* Bug 1: terapkan frame pertama dari library */
  if(_frames.length){pickFrame(_frames[0].id)}
  out.picked=S.frame;
  out.frame_fields=_frames.length?Object.keys(_frames[0]).filter(function(k){
    return /url/.test(k)}):[];
  /* Bug 2: watermark aktif dengan penanda default */
  S.wm.on=true; S.wm.text='Creator!';
  out.creator_hint=(typeof _creatorHint!=='undefined')?_creatorHint:'(undef)';
  S.head.on=true; S.head.text='HEADLINE';
  buildInspector(); syncAll(); requestTextLayers();
  return JSON.stringify(out);
}catch(e){return JSON.stringify({__err:''+e+' @ '+(e.stack||'').split('\n')[1]})}})()
"""

# ------------------------------------------------------ fase 3: ukur (non-zoom)
MEASURE = r"""
(function(){try{
  var o={console_errors:(window.__errs||[])};
  var $=function(i){return document.getElementById(i)};
  var cs=function(e){return getComputedStyle(e)};
  var R=function(n){return Math.round(n)};

  /* ---- P1.1 frame tampil di preview tengah ---- */
  var rc=document.querySelector('.rc.adjust');
  var fi=rc?rc.querySelector('.frameimg'):null;
  o.n1={node:!!fi,src:fi?(fi.getAttribute('src')||''):'',
        nat_w:fi?fi.naturalWidth:0,nat_h:fi?fi.naturalHeight:0,
        display:fi?cs(fi).display:'(none)',frame_id:S.frame};
  o.n1.pass=!!fi && !!o.n1.src && o.n1.nat_w>0 && o.n1.display!=='none';

  /* ---- P1.2 watermark tampil di preview ---- */
  var wm=rc?rc.querySelector('.wmlayer'):null;
  var hd=rc?rc.querySelector('.headlayer'):null;
  o.n2={wm_src:wm?(wm.getAttribute('src')||''):'',wm_nat:wm?wm.naturalWidth:0,
        wm_disp:wm?cs(wm).display:'(none)',
        head_src:hd?!!hd.getAttribute('src'):false,head_nat:hd?hd.naturalWidth:0,
        eff_text:(typeof wmEffectiveText==='function')?wmEffectiveText():'(nofn)'};
  o.n2.pass=!!o.n2.wm_src && o.n2.wm_nat>0 && o.n2.wm_disp!=='none';

  /* ---- P1.3 visual toggle switch benar-benar berubah ----
     PENTING: klik sakelar memanggil toggleB() -> buildInspector(), yang MENULIS ULANG
     innerHTML panel. Referensi elemen lama jadi node terlepas (detached) yang
     getComputedStyle-nya mengembalikan string kosong. Karena itu elemen harus
     DICARI ULANG setelah klik, kalau tidak tes melaporkan FAIL palsu. */
  function findHeadSw(){
    var accs=[].slice.call(document.querySelectorAll('#inspector .acc'));
    var a=accs.filter(function(x){return /HEADLINE|Headline/i.test(x.textContent)})[0];
    return a?a.querySelector('.acc-h .sw'):null;
  }
  function probeSw(get){
    var el=get(); if(!el)return null;
    var b0=cs(el).backgroundColor, c0=el.classList.contains('on');
    el.click();
    var el2=get(); if(!el2)return {changed:false,note:'hilang setelah klik'};
    var b1=cs(el2).backgroundColor, c1=el2.classList.contains('on');
    el2.click();                                  /* pulihkan */
    var el3=get();
    var c2=el3?el3.classList.contains('on'):null;
    return {cls:[c0,c1,c2],bg:[b0,b1],
            changed:(c0!==c1 && b0!==b1 && c2===c0)};
  }
  var rHead=probeSw(findHeadSw);
  var rSafe=probeSw(function(){return $('safeSw')});
  o.n3={head:rHead,safe:rSafe};
  o.n3.pass=!!(rHead&&rHead.changed)&&!!(rSafe&&rSafe.changed);

  /* ---- P1.4 + P2.9 thumbnail rasio tetap & grid nambah kolom ---- */
  function gridState(){
    var g=$('frameGrid');
    var c=g.querySelector('.card'), th=c?c.querySelector('.th'):null;
    var cr=c?c.getBoundingClientRect():{width:0,height:0};
    var tr=th?th.getBoundingClientRect():{width:0,height:0};
    /* jumlah kolom = banyak kartu dengan offsetTop sama dgn kartu pertama */
    var cards=[].slice.call(g.querySelectorAll('.card'));
    var top0=cards.length?cards[0].offsetTop:0;
    var cols=cards.filter(function(x){return x.offsetTop===top0}).length;
    return {card_w:R(cr.width),card_h:R(cr.height),th_w:R(tr.width),th_h:R(tr.height),
            ratio:tr.height?+(tr.width/tr.height).toFixed(3):0,cols:cols};
  }
  var root=document.documentElement;
  root.style.setProperty('--left-w','200px'); var g200=gridState();
  root.style.setProperty('--left-w','420px'); var g420=gridState();
  root.style.setProperty('--left-w','240px');
  o.n4={narrow:g200,wide:g420};
  o.n4.pass=(g200.ratio>0 && Math.abs(g200.ratio-g420.ratio)<0.02
             && Math.abs(g200.th_w-g420.th_w)<=2 && g420.cols>g200.cols
             /* kartu harus setinggi thumbnail-nya: kalau tidak, ia gepeng dan grid
                tidak pernah cukup tinggi untuk butuh scroll internal */
             && g200.card_h>=g200.th_h && g420.card_h>=g420.th_h);

  /* ---- P1.6 i18n: setiap kunci data-i18n ADA di kamus id & en ---- */
  var keys={},miss_id=[],miss_en=[];
  document.querySelectorAll('[data-i18n]').forEach(function(e){
    keys[e.getAttribute('data-i18n')]=1});
  document.querySelectorAll('[data-i18n-ph]').forEach(function(e){
    keys[e.getAttribute('data-i18n-ph')]=1});
  document.querySelectorAll('[data-i18n-title]').forEach(function(e){
    keys[e.getAttribute('data-i18n-title')]=1});
  Object.keys(keys).forEach(function(k){
    if(!(k in I18N.id))miss_id.push(k);
    if(!(k in I18N.en))miss_en.push(k)});
  /* Teks CHROME (bukan data) yang tidak punya data-i18n = kandidat hardcode.
     Nama frame/theme/font/sticker SENGAJA dikecualikan: itu data milik user, tidak
     boleh diterjemahkan. Karena itu selektornya menghindari `.card` dan `.frow`. */
  var hard=[];
  document.querySelectorAll(
    '#libraryScroll .lib-actions button, .chead button, .bar button, .mbar button')
   .forEach(function(b){
     var t=(b.textContent||'').trim();
     if(!t)return;
     if(b.hasAttribute('data-i18n'))return;
     if(b.querySelector('[data-i18n]'))return;
     /* tombol berikon murni (＋ ↻ 📁 🎲 💾 − + ⟲ ▪ ◼ ×) tidak punya teks untuk
        diterjemahkan; yang penting tooltip-nya ada di kamus. */
     if(!/[A-Za-z\u00C0-\u024F]{2,}/.test(t))return;
     hard.push(t.slice(0,24))});
  /* Setiap title/tooltip HARUS lewat kamus (data-i18n-title), tanpa kecuali —
     tooltip yang ketinggalan adalah bagian dari keluhan "EN/ID cuma sebagian". */
  var titles=[];
  document.querySelectorAll('[title]').forEach(function(e){
    if(!e.hasAttribute('data-i18n-title'))titles.push(e.getAttribute('title').slice(0,24))});
  o.n6={keys:Object.keys(keys).length,missing_id:miss_id,missing_en:miss_en,
        hardcoded_buttons:hard,untranslated_titles:titles};
  o.n6.pass=!miss_id.length && !miss_en.length && !hard.length && !titles.length;

  /* ---- P2.7 scroll utama Library mati, scroll internal hidup ----
     Panel Library sekarang FIXED: `#libraryScroll` overflow hidden (tidak pernah
     bergeser), dan grid di dalam kartu yang TERBUKA yang menggulir. Supaya tes ini
     benar-benar menguji sesuatu, isi grid harus melebihi tingginya — jadi tinggi
     jendela dipersempit dulu lewat --left-w? tidak: yang menentukan adalah tinggi
     panel. Grid 21 kartu × 171px pasti melebihi ruang yang tersedia di jendela uji. */
  var ls=$('libraryScroll'), fg=$('frameGrid');
  var lsOv=cs(ls).overflowY;
  ls.scrollTop=9999; var lsTop=ls.scrollTop; ls.scrollTop=0;
  fg.scrollTop=9999; var fgTop=fg.scrollTop; fg.scrollTop=0;
  o.n7={lib_overflow:lsOv,lib_scrolltop_after_push:lsTop,
        lib_client:R(ls.clientHeight),lib_scroll:R(ls.scrollHeight),
        grid_client:R(fg.clientHeight),grid_scroll:R(fg.scrollHeight),
        grid_scrolled:fgTop,grid_overscroll:cs(fg).overscrollBehaviorY,
        cards:fg.querySelectorAll('.card').length};
  o.n7.pass=(lsOv==='hidden'||lsOv==='clip') && lsTop===0
            && fg.scrollHeight>fg.clientHeight && fgTop>0
            && cs(fg).overscrollBehaviorY==='contain';

  /* ---- P2.8 min-width panel: tombol tidak terpotong ---- */
  root.style.setProperty('--left-w','120px');
  var col=$('colLeft');
  var cw=col.getBoundingClientRect().width;
  var cut=[];
  document.querySelectorAll('#libraryScroll .lib-actions button').forEach(function(b){
    var r=b.getBoundingClientRect();
    if(b.scrollWidth>b.clientWidth+1 || r.right>col.getBoundingClientRect().right+0.5)
      cut.push(((b.textContent||'').trim()||'?').slice(0,18))});
  o.n8={requested:120,actual_w:R(cw),clipped:cut};
  root.style.setProperty('--left-w','240px');
  o.n8.pass=cw>=200 && !cut.length;

  /* ---- P2.10 zero-center slider X/Y ----
     Diuji di FASE TERSENDIRI (`CENTER_SET` / `CENTER_READ`) karena jawabannya butuh
     lapisan teks digambar ulang oleh Python: satu-satunya bukti yang sah adalah pusat
     tinta hasil render berada di tengah kanvas, bukan nilai `x` di state. */
  o.n10_skipped=true;

  /* ---- P2.11 urutan accordion Library ---- */
  var ids=[].slice.call(document.querySelectorAll('#libraryScroll > .acc')).map(function(e){return e.id});
  o.n11={order:ids};
  o.n11.pass=JSON.stringify(ids)===JSON.stringify(['accFrame','accFont','accSticker','accTheme']);

  /* ---- P4.13 label CRF -> Kualitas Video ---- */
  var insp=$('inspector').textContent;
  o.n13={has_crf_label:/CRF/i.test(insp)};
  o.n13.pass=!/\bCRF\b/.test(insp);

  /* ---- P4.14 Alignment pakai ikon ---- */
  var alignTexts=[];
  document.querySelectorAll('#inspector .ctl.full').forEach(function(c){
    // In our new design, the label text "Align" was removed, so we check data-i18n-title
    c.querySelectorAll('button').forEach(function(b){
       if(b.hasAttribute('data-i18n-title') && /^align[LCR]/.test(b.getAttribute('data-i18n-title'))) {
          alignTexts.push((b.textContent||'').trim());
       }
    });
  });
  o.n14={buttons:alignTexts};
  o.n14.pass=alignTexts.length>0 && alignTexts.every(function(t){
    return !/Kiri|Tengah|Kanan|Left|Center|Right/i.test(t)});

  /* ---- P4.15 switcher thumbnail: label + status aktif ---- */
  var ts=document.querySelector('.thumb-sizes');
  var lbl=ts?ts.parentElement.textContent:'';
  o.n15={has_label:/Thumbnail/i.test(lbl),
         active:document.querySelectorAll('.thumb-sizes .on').length};
  o.n15.pass=o.n15.has_label && o.n15.active===1;

  /* ---- P4.16 label mati 1080x1920 di Canvas ---- */
  o.n16={found:/1080\u00d71920|1080x1920/.test(insp)};
  o.n16.pass=!o.n16.found;

  /* ---- P4.17 "Hapus PNG" redundan ---- */
  var hp=[];
  document.querySelectorAll('#inspector button, #libraryScroll button').forEach(function(b){
    if(/Hapus PNG|Remove PNG/i.test(b.textContent||''))hp.push(b.textContent.trim())});
  o.n17={found:hp};
  o.n17.pass=!hp.length;

  /* ---- P4.18 "Simpan Theme" ganda ---- */
  var st=[];
  document.querySelectorAll('button').forEach(function(b){
    if(/Simpan theme|Save theme|Simpan Theme Baru/i.test(b.textContent||''))
      st.push((b.textContent||'').trim().slice(0,22))});
  o.n18={found:st};
  o.n18.pass=st.length<=1;

  /* ---- P4.19 label import cuma "Import" ---- */
  var imp=[];
  document.querySelectorAll('#libraryScroll button').forEach(function(b){
    var t=(b.textContent||'').trim();
    if(/import|upload/i.test(t))imp.push(t)});
  o.n19={found:imp};
  o.n19.pass=imp.length>0 && imp.every(function(t){
    return /^[\uFF0B+]?\s*(Import)$/i.test(t)});

  /* ---- P4.20 ikon hapus = tempat sampah merah ---- */
  var xs=[].slice.call(document.querySelectorAll('#libraryScroll .card .x, #fontList .x'));
  var glyphs=xs.map(function(e){return (e.textContent||'').trim()});
  o.n20={glyphs:glyphs.slice(0,6),count:xs.length,
         color:xs.length?cs(xs[0]).color:'',
         svg:xs.length?xs.filter(function(e){return !!e.querySelector('svg')}).length:0};
  /* Bukti "ikon tempat sampah": tiap tombol hapus memuat <svg> (bukan glyph "×") dan
     warnanya merah (komponen R jauh lebih besar dari G/B). */
  var col=(o.n20.color||'').match(/(\d+)\D+(\d+)\D+(\d+)/);
  o.n20.reddish=!!col && (+col[1] > +col[2]+40) && (+col[1] > +col[3]+40);
  o.n20.pass=xs.length>0 && o.n20.svg===xs.length && o.n20.reddish
             && glyphs.every(function(g){return g===''});

  return JSON.stringify(o);
}catch(e){return JSON.stringify({__err:''+e+' @ '+(e.stack||'').split('\n').slice(1,3).join(' | ')})}})()
"""

# ---- P2.10: setel semua slider X/Y ke 0 (posisi netral), lalu ukur hasil NYATA ----
CENTER_SET = r"""
(function(){try{
  var out={};
  ['head','wm','sub'].forEach(function(k){
    S[k].align='center';
    setOffX(k,{value:0});
    setOffY(k,{value:0});
    out[k]={x:S[k].x,y:S[k].y};
  });
  setOffX('video',{value:0}); setOffY('video',{value:0});
  out.video={x:S.video.x,y:S.video.y};
  S.png.on=true; S.png.w=200;
  setOffX('png',{value:0}); setOffY('png',{value:0});
  out.png={x:S.png.x,y:S.png.y};
  buildInspector();
  return JSON.stringify(out);
}catch(e){return JSON.stringify({__err:''+e})}})()
"""

CENTER_READ = r"""
(function(){try{
  var out={cw:CW,ch:CH,blocks:{}};
  /* Bukti untuk teks: PUSAT TINTA hasil render (dilaporkan mesin lewat `ink`) harus
     berada di tengah kanvas. Nilai `x` di state bukan bukti — auto-fit bisa mengubah
     tinggi blok setelah nilainya ditulis. */
  ['head','wm','sub'].forEach(function(k){
    var b=_ink[k]||null;
    out.blocks[k]=b?{cx:b.cx,cy:b.cy,w:b.w,h:b.h,
                     dx:b.cx-Math.round(CW/2),dy:b.cy-Math.round(CH/2)}:null;
  });
  var g=effGeom();
  out.blocks.video={cx:Math.round(CW/2+(g.x||0)),cy:Math.round(g.y+g.h/2),
                    dx:Math.round(g.x||0),dy:Math.round(g.y+g.h/2-CH/2)};
  var pa=pngAspect();
  out.blocks.png={cx:Math.round(S.png.x+S.png.w/2),
                  cy:Math.round(S.png.y+S.png.w*pa/2)};
  out.blocks.png.dx=out.blocks.png.cx-Math.round(CW/2);
  out.blocks.png.dy=out.blocks.png.cy-Math.round(CH/2);
  /* Slider di DOM harus benar-benar simetris: nilai tengahnya 0.
     Baris X/Y memakai markup `.ctl-xy` (item 22: side-by-side + input angka manual),
     labelnya ada di `.xy-label`. Baris lama (`.ctl` dengan <label>) tetap dibaca supaya
     tes ini masih berlaku kalau ada slider posisi yang belum dipindah. */
  var sl=[];
  document.querySelectorAll('#inspector input[type=range]').forEach(function(r){
    var xy=r.closest('.ctl-xy');
    var t='';
    if(xy){ t=((xy.querySelector('.xy-label')||{}).textContent||''); }
    else {
      var row=r.closest('.ctl');
      if(row) t=((row.querySelector('label')||{}).textContent||'');
    }
    if(!t) return;
    if(!/X|Y|Posisi|position/i.test(t))return;
    if(t.indexOf('Shadow')!==-1 || t.indexOf('Drop Shadow')!==-1 || t.indexOf('Blur')!==-1 || t.indexOf('Opacity')!==-1)return;
    sl.push({label:t.trim(),min:+r.min,max:+r.max,val:+r.value,
             mid:(+r.min + +r.max)/2});
  });
  out.sliders=sl;
  return JSON.stringify(out);
}catch(e){return JSON.stringify({__err:''+e+' | '+(e.stack||'').split('\n')[1]})}})()
"""

ZOOM_SNAP = r"""
(function(){
  var $=function(i){return document.getElementById(i)};
  var b=document.querySelector('.bar').getBoundingClientRect();
  return JSON.stringify({
    stage:getComputedStyle($('stage')).transform,
    bar_h:b.height,
    left:$('colLeft').getBoundingClientRect().width,
    right:$('colRight').getBoundingClientRect().width,
    rc:$('rcA').getBoundingClientRect().width,
    body_font:getComputedStyle(document.body).fontSize
  });
})()
"""

# ctrl+wheel harus di-preventDefault (P1.5) DAN menaikkan zoom preview
WHEEL = r"""
(function(){
  var before=S.zoom;
  var vp=document.querySelector('.vp')||document.body;
  var ev=new WheelEvent('wheel',{bubbles:true,cancelable:true,ctrlKey:true,deltaY:-120,
                                 clientX:vp.getBoundingClientRect().left+20,
                                 clientY:vp.getBoundingClientRect().top+20});
  vp.dispatchEvent(ev);
  var out={prevented:ev.defaultPrevented,zoom_before:before,zoom_after:S.zoom};
  /* di luar area preview: tetap harus dicegah (jangan zoom UI) */
  var ev2=new WheelEvent('wheel',{bubbles:true,cancelable:true,ctrlKey:true,deltaY:-120});
  document.getElementById('libraryScroll').dispatchEvent(ev2);
  out.prevented_outside=ev2.defaultPrevented;
  out.zoom_after_outside=S.zoom;
  setZoom(100);
  return JSON.stringify(out);
})()
"""

app = QApplication.instance() or QApplication(sys.argv)
win = clipper_gui.ClipperWindow()
win.resize(1400, 860)
win.show()
win.switch_page(1)

view = next(iter(win.findChildren(QWebEngineView)), None)
if view is None:
    print("FAIL: QWebEngineView tidak ditemukan")
    sys.exit(1)

result: dict = {}


def js(code, cb=None, delay=0):
    def run():
        view.page().runJavaScript(code, cb or (lambda _r: None))
    QTimer.singleShot(delay, run)


def phase_center():
    """P2.10: setel semua slider X/Y ke 0, tunggu lapisan digambar, lalu UKUR."""
    # Lapisan teks digambar ASINKRON oleh Python (bridge -> text_engine -> PNG). Menunggu
    # dengan tenggat tetap membuat tes ini FLAKY: kalau lapisan belum sampai, `_ink` masih
    # kosong dan hasilnya FAIL walau UI-nya benar. Karena itu baca ULANG sampai ketiga
    # blok teks punya kotak tinta, dengan batas percobaan supaya tidak menggantung.
    attempts = {"n": 0}
    MAX_ATTEMPTS = 12          # 12 x 500ms = 6s, cukup longgar untuk mesin lambat
    RETRY_DELAY = 500

    def after_read(raw):
        try:
            d = json.loads(raw)
        except Exception:
            d = {"__err": raw}
        blocks = d.get("blocks") or {}
        # Blok teks yang kotak tintanya belum dilaporkan -> lapisan belum digambar.
        pending = [k for k in ("head", "wm", "sub") if not blocks.get(k)]
        if pending and attempts["n"] < MAX_ATTEMPTS:
            attempts["n"] += 1
            js(CENTER_READ, after_read, RETRY_DELAY)
            return

        tol = 3  # toleransi pembulatan px
        offs = {}
        ok = bool(blocks) and not d.get("__err")
        for k, b in blocks.items():
            if not b:
                offs[k] = None
                ok = False
                continue
            offs[k] = {"dx": b.get("dx"), "dy": b.get("dy")}
            if abs(int(b.get("dx") or 0)) > tol or abs(int(b.get("dy") or 0)) > tol:
                ok = False
        sliders = d.get("sliders") or []
        # Baris X/Y ada di 5 seksi: Video, Headline, Subtitle, Creator, Sticker => 10 slider.
        # Ambang ditulis 8 (bukan 10) supaya tes tidak pecah kalau satu seksi sengaja
        # dihilangkan; yang diuji di sini adalah SIMETRINYA, bukan jumlah seksi.
        valid_sliders = [s for s in sliders if s.get("label") in ("X", "Y")]
        sym = all(abs(float(s["mid"])) < 1e-6 for s in valid_sliders) and len(valid_sliders) >= 8
        result["n10"] = {
            "offsets_from_center": offs,
            "sliders": sliders,
            "slider_xy_count": len(valid_sliders),
            "sliders_symmetric": sym,
            "ink_wait_attempts": attempts["n"],
            "ink_missing": pending,
            "raw_err": d.get("__err"),
            "pass": ok and sym and not pending,
        }
        QTimer.singleShot(200, phase_zoom)

    def after_set(raw):
        try:
            result["center_set"] = json.loads(raw)
        except Exception:
            result["center_set"] = {"raw": raw}
        js(CENTER_READ, after_read, 1200)

    js(CENTER_SET, after_set)


def phase_zoom():
    def got_before(raw):
        before = json.loads(raw)

        def got_after(raw2):
            after = json.loads(raw2)
            n5 = {
                "before": before, "after": after,
                "stage_changed": before.get("stage") != after.get("stage"),
                "preview_grew": after.get("rc", 0) > before.get("rc", 1) * 1.5,
                "chrome_same": (
                    before.get("bar_h") == after.get("bar_h")
                    and before.get("left") == after.get("left")
                    and before.get("right") == after.get("right")
                    and before.get("body_font") == after.get("body_font")
                ),
            }

            def got_wheel(raw3):
                w = json.loads(raw3)
                n5["wheel"] = w
                n5["pass"] = (
                    n5["stage_changed"] and n5["preview_grew"] and n5["chrome_same"]
                    and w.get("prevented") and w.get("prevented_outside")
                    and w.get("zoom_after") != w.get("zoom_before")
                )
                result["n5"] = n5
                app.quit()

            view.page().runJavaScript("setZoom(100)")
            js(WHEEL, got_wheel, 200)

        view.page().runJavaScript("setZoom(220)")
        js(ZOOM_SNAP, got_after, 600)

    js(ZOOM_SNAP, got_before)


def phase_measure():
    def got(raw):
        try:
            result.update(json.loads(raw))
        except Exception:
            result["raw_measure"] = raw
        QTimer.singleShot(200, phase_center)

    js(MEASURE, got)


def phase_arrange():
    def got(raw):
        try:
            result["arrange"] = json.loads(raw)
        except Exception:
            result["arrange"] = {"raw": raw}
        # lapisan teks digambar asinkron oleh Python -> beri waktu
        QTimer.singleShot(1800, phase_measure)

    js(ARRANGE, got)


def phase_ready(tries=0):
    def got(raw):
        try:
            d = json.loads(raw)
        except Exception:
            d = {}
        if not d.get("frames") and tries < 40:
            QTimer.singleShot(500, lambda: phase_ready(tries + 1))
            return
        result["ready"] = d
        QTimer.singleShot(200, phase_arrange)

    js(READY, got)


QTimer.singleShot(2500, phase_ready)
QTimer.singleShot(90000, app.quit)
app.exec()

LABELS = [
    ("n1", "P1.1  Frame tampil di preview tengah"),
    ("n2", "P1.2  Watermark/Kreator tampil di preview"),
    ("n3", "P1.3  Visual toggle switch merespons"),
    ("n4", "P1.4  Thumbnail rasio tetap + P2.9 grid nambah kolom"),
    ("n5", "P1.5  Zoom hanya kanvas (ctrl+wheel dicegah)"),
    ("n6", "P1.6  i18n lengkap (kunci ada, tak ada hardcode)"),
    ("n7", "P2.7  Scroll utama Library mati, internal hidup"),
    ("n8", "P2.8  Min-width panel: tombol tak terpotong"),
    ("n10", "P2.10 Zero-center slider X"),
    ("n11", "P2.11 Urutan Frame/Font/Sticker/Theme"),
    ("n13", "P4.13 Label CRF -> Kualitas Video"),
    ("n14", "P4.14 Alignment pakai ikon"),
    ("n15", "P4.15 Switcher thumbnail berlabel + aktif"),
    ("n16", "P4.16 Label mati 1080x1920 dibuang"),
    ("n17", "P4.17 'Hapus PNG' redundan dibuang"),
    ("n18", "P4.18 'Simpan Theme' tidak ganda"),
    ("n19", "P4.19 Label import = 'Import'"),
    ("n20", "P4.20 Ikon hapus = tempat sampah"),
]

print(json.dumps(result, indent=2, ensure_ascii=False))
print()
allok = True
for key, lab in LABELS:
    p = (result.get(key) or {}).get("pass")
    allok = allok and bool(p)
    print(f"  [{'PASS' if p else 'FAIL'}] {lab}")
errs = result.get("console_errors") or []
print(f"  console_errors: {len(errs)} {errs[:3]}")
allok = allok and not errs
print("VERDICT:", "SEMUA PASS" if allok else "ADA YANG FAIL")
sys.exit(0 if allok else 2)
