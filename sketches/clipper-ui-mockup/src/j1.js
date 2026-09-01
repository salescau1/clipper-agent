/* ============ i18n ============ */
const I18N={
 id:{random:"Random",saveTheme:"Simpan theme",
  saving:"Menyimpan draf...",saved:"Draf tersimpan · simpan sebagai Theme untuk dipakai tab Run",
  library:"Library",frames:"Frame",themes:"Theme",style:"Style",safeArea:"Safe area",
  adjustment:"Adjustment",output:"Output",
  inputAdjustment:"Input Adjustment",output916:"Output",
  secCanvas:"Canvas",secVideo:"Video",secSub:"Subtitle",secHead:"Headline",secWm:"Creator",
  secPng:"Sticker",secFont:"Font",secExport:"Export Option",
  ratio:"Rasio",sourceRatio:"Rasio sumber",scale:"Skala",ypos:"Posisi Y",xpos:"Posisi X",
  xoff:"Geser X",radius:"Sudut",
  center:"Tengah",reset:"Reset",font:"Font",size:"Ukuran",outline:"Outline",outlineColor:"Warna outline",
  opacity:"Transparansi",scaleHint:"0% = video utuh (tidak terpotong) · 300% = penuhi kanvas",
  shadow:"Shadow",color:"Warna",animation:"Animasi",wordsPerLine:"Kata per baris",text:"Teks",
  outer:"Outer",inner:"Inner",off:"Off",strokeOff:"Tanpa stroke",
  auto:"Auto",custom:"Kustom",srtDefault:"Ikut SRT",word:"kata",
  wpl1:"1 kata — SUBTITLE",wpl3:"3 kata — SUBTITLE SUBTITLE SUBTITLE",
  wpl5:"5 kata — SUBTITLE ×5",
  wplHint:"Contoh di preview memakai jumlah kata ini. Ketik teks sendiri di kotak Teks untuk menggantinya.",
  upload:"Import",removePng:"Hapus PNG",importFont:"Import",openFolder:"Buka folder",
  import:"Import",thumbSize:"Thumbnail Size",thumbSmall:"Kecil",thumbNormal:"Normal",
  resizeLib:"Tarik untuk ubah lebar Library",trash:"Hapus",
  refresh:"Refresh",quality:"Kualitas video",qualityHint:"Angka kecil = lebih tajam (file lebih besar)",
  speed:"Kecepatan encode",
  noFrame:"Belum ada frame. Klik ＋ untuk impor PNG.",
  noTheme:"Belum ada theme. Atur gaya lalu klik ＋.",
  themeName:"Nama theme:",themeSaved:"Theme disimpan: ",themeLoaded:"Theme dipakai: ",
  themeDeleted:"Theme dihapus: ",frameDeleted:"Frame dihapus: ",fontDeleted:"Font dihapus: ",
  askDelFrame:"Hapus frame ini dari library?",askDelTheme:"Hapus theme ini?",askDelFont:"Hapus font ini?",
  askOverwrite:"Nama \"%s\" sudah dipakai. Timpa theme itu?\n\nBatal = ganti nama.",
  guiOnly:"Hanya tersedia di dalam Clipper GUI",lineGap:"Jarak baris",
  noPng:"Belum ada stiker/PNG",pngMissing:"File PNG overlay tidak ditemukan, dimatikan",
  maxLines:"Maks baris",autoFit:"Dikecilkan otomatis jadi",shadowX:"Geser X",shadowY:"Geser Y",
  align:"Perataan",alignLeft:"Kiri",alignCenter:"Tengah",alignRight:"Kanan",nudgeX:"Geser X halus",
  activeColor:"Warna kata aktif",
  wmAutoOn:"Otomatis: hasil render pakai \"%s\" (nama kreator video).",
  wmAutoOff:"Teks tetap. Tulis \"Creator!\" untuk ikut nama kreator.",
  shadowBlur:"Blur",shadowColor:"Warna bayangan",layerOrder:"Urutan lapisan",
  blurBg:"Blur background",blurRadius:"Tingkat blur",
  secIntro:"Intro Cover",introDur:"Durasi",introFade:"Fade out",
  introBg:"Gambar cover",introNoBg:"Belum ada gambar",introHead:"Tampilkan headline",
  introWm:"Tampilkan nama creator",
  orderStrokeFill:"Outline di bawah",orderFillStroke:"Outline di atas",
  shadowSameWarn:"Warna bayangan sama dgn outline — efek 3D tidak terlihat. Pakai warna beda.",
  fontCount:" font",builtin:"bawaan",none:"Tidak ada",pop:"Pop",fade:"Fade",up:"Naik",
  wordAnim:"Per kata",karaoke:"Karaoke",failed:"Gagal: ",randomized:"Gaya diacak"},
 en:{random:"Random",saveTheme:"Save theme",
  saving:"Saving draft...",saved:"Draft saved · save as a Theme to use it in the Run tab",
  library:"Library",frames:"Frames",themes:"Themes",style:"Style",safeArea:"Safe area",
  adjustment:"Adjustment",output:"Output",
  inputAdjustment:"Input Adjustment",output916:"Output",
  secCanvas:"Canvas",secVideo:"Video",secSub:"Subtitle",secHead:"Headline",secWm:"Creator",
  secPng:"Sticker",secFont:"Fonts",secExport:"Export Option",
  ratio:"Ratio",sourceRatio:"Source ratio",scale:"Scale",ypos:"Y position",xpos:"X position",
  xoff:"X offset",radius:"Radius",
  center:"Center",reset:"Reset",font:"Font",size:"Size",outline:"Outline",outlineColor:"Outline color",
  opacity:"Opacity",scaleHint:"0% = whole video (nothing cropped) · 300% = fill the canvas",
  shadow:"Shadow",color:"Color",animation:"Animation",wordsPerLine:"Words per line",text:"Text",
  outer:"Outer",inner:"Inner",off:"Off",strokeOff:"No stroke",
  auto:"Auto",custom:"Custom",srtDefault:"Follow SRT",word:"words",
  wpl1:"1 word — SUBTITLE",wpl3:"3 words — SUBTITLE SUBTITLE SUBTITLE",
  wpl5:"5 words — SUBTITLE ×5",
  wplHint:"The preview sample uses this word count. Type your own text in the Text box to replace it.",
  upload:"Import",removePng:"Remove PNG",importFont:"Import",openFolder:"Open folder",
  import:"Import",thumbSize:"Thumbnail Size",thumbSmall:"Small",thumbNormal:"Normal",
  resizeLib:"Drag to resize the Library panel",trash:"Delete",
  refresh:"Refresh",quality:"Video quality",qualityHint:"Lower number = sharper (bigger file)",
  speed:"Encode speed",
  noFrame:"No frames yet. Click ＋ to import a PNG.",
  noTheme:"No themes yet. Style it, then click ＋.",
  themeName:"Theme name:",themeSaved:"Theme saved: ",themeLoaded:"Theme applied: ",
  themeDeleted:"Theme deleted: ",frameDeleted:"Frame deleted: ",fontDeleted:"Font deleted: ",
  askDelFrame:"Delete this frame from the library?",askDelTheme:"Delete this theme?",askDelFont:"Delete this font?",
  askOverwrite:"The name \"%s\" is taken. Overwrite that theme?\n\nCancel = rename.",
  guiOnly:"Only available inside the Clipper GUI",lineGap:"Line gap",
  noPng:"No sticker/PNG yet",pngMissing:"Overlay PNG file not found, disabled",
  maxLines:"Max lines",autoFit:"Auto-shrunk to",shadowX:"Offset X",shadowY:"Offset Y",
  align:"Align",alignLeft:"Left",alignCenter:"Center",alignRight:"Right",nudgeX:"Nudge X",
  activeColor:"Active word colour",
  wmAutoOn:"Automatic: the render will use \"%s\" (the video's creator name).",
  wmAutoOff:"Fixed text. Type \"Creator!\" to follow the creator name.",
  shadowBlur:"Blur",shadowColor:"Shadow color",layerOrder:"Layer order",
  blurBg:"Blur background",blurRadius:"Blur amount",
  secIntro:"Intro Cover",introDur:"Duration",introFade:"Fade out",
  introBg:"Cover image",introNoBg:"No image yet",introHead:"Show headline",
  introWm:"Show creator name",
  orderStrokeFill:"Outline below",orderFillStroke:"Outline above",
  shadowSameWarn:"Shadow colour matches the outline — no 3D depth. Use a different colour.",
  fontCount:" fonts",builtin:"built-in",none:"None",pop:"Pop",fade:"Fade",up:"Slide up",
  wordAnim:"Word by word",karaoke:"Karaoke",failed:"Failed: ",randomized:"Style randomized"}
};
let LANG="id";
function L(k){return (I18N[LANG]||I18N.id)[k]||(I18N.id[k]||k)}
/* Terjemahan menyentuh TIGA tempat: textContent (`data-i18n`), placeholder
   (`data-i18n-ph`), dan atribut title/tooltip (`data-i18n-title`). Tooltip yang
   ketinggalan adalah bagian dari keluhan "EN/ID cuma mengubah sebagian teks". */
function applyI18n(){
 document.querySelectorAll('[data-i18n]').forEach(e=>{e.textContent=L(e.getAttribute('data-i18n'))});
 document.querySelectorAll('[data-i18n-ph]').forEach(e=>{e.placeholder=L(e.getAttribute('data-i18n-ph'))});
 document.querySelectorAll('[data-i18n-title]').forEach(e=>{e.title=L(e.getAttribute('data-i18n-title'))});
 buildInspector(); renderFrames(); renderThemes(); renderFontList(); renderOverlayList();
 updateViewLabel();
}
function applyLangFromHost(l){LANG=(l==='en')?'en':'id';applyI18n()}
function setLang(l){applyLangFromHost(l);
 if(B&&B.set_language)B.set_language(LANG,function(){});}

/* ============ helpers ============ */
const $=id=>document.getElementById(id);
let B=null; // bridge
function toast(msg){const e=$('toast');e.textContent=msg;e.classList.add('on');
 clearTimeout(window.__t);window.__t=setTimeout(()=>e.classList.remove('on'),2000)}
function num(v,d){const n=parseFloat(v);return isNaN(n)?d:n}
function clamp(v,a,b){return Math.max(a,Math.min(b,v))}
function hex(c){c=(c||'').trim();if(!c)return '#FFFFFF';
 if(c[0]==='#')return (c.length===4?('#'+c[1]+c[1]+c[2]+c[2]+c[3]+c[3]):c).toUpperCase();
 const m=c.match(/rgba?\((\d+)[,\s]+(\d+)[,\s]+(\d+)/i);
 return m?('#'+[1,2,3].map(i=>(+m[i]).toString(16).padStart(2,'0')).join('').toUpperCase()):'#FFFFFF'}
function hsl2hex(h,s,l){s/=100;l/=100;
 const k=n=>(n+h/30)%12,a=s*Math.min(l,1-l),f=n=>l-a*Math.max(-1,Math.min(k(n)-3,Math.min(9-k(n),1)));
 return '#'+[f(0),f(8),f(4)].map(x=>Math.round(255*x).toString(16).padStart(2,'0')).join('').toUpperCase()}
function hex2hsl(H){const h=hex(H);const r=parseInt(h.slice(1,3),16)/255,g=parseInt(h.slice(3,5),16)/255,b=parseInt(h.slice(5,7),16)/255;
 const mx=Math.max(r,g,b),mn=Math.min(r,g,b),d=mx-mn;let hu=0;
 if(d){if(mx===r)hu=((g-b)/d)%6;else if(mx===g)hu=(b-r)/d+2;else hu=(r-g)/d+4;hu*=60;if(hu<0)hu+=360}
 const l=(mx+mn)/2,s=d?d/(1-Math.abs(2*l-1)):0;
 return{h:Math.round(hu),s:Math.round(s*100),l:Math.round(l*100)}}
function lum(H){const h=hex(H);const c=[1,3,5].map(i=>parseInt(h.substr(i,2),16)/255);
 return .2126*c[0]+.7152*c[1]+.0722*c[2]}
function autoStroke(fill){return lum(fill)>.6?'#000000':'#FFFFFF'}
