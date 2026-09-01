"""
Rakit index.html Customize dari potongan di src/.

index.html adalah HASIL BUILD — jangan diedit langsung; edit file di src/ lalu:

    .venv\\Scripts\\python.exe sketches/clipper-ui-mockup/build.py

Urutan: p1.html (head+CSS dasar) + p2.css + p3.css + p4.body.html + j1..j6.js
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
UI = HERE / "src"
OUT = HERE / "index.html"

head = (UI / "p1.html").read_text(encoding="utf-8")   # <!doctype> ... <style> kedua
# p1 sudah menutup <style>-nya sendiri; buang penutup itu agar CSS lanjutan bisa disisipkan.
head = head.rstrip()
assert head.endswith("</style>"), head[-40:]
head = head[: -len("</style>")].rstrip()
css2 = (UI / "p2.css").read_text(encoding="utf-8")
css3 = (UI / "p3.css").read_text(encoding="utf-8")
body = (UI / "p4.body.html").read_text(encoding="utf-8")
js = "\n".join((UI / f"j{i}.js").read_text(encoding="utf-8") for i in range(1, 7))

html = (
    head.rstrip()
    + "\n" + css2.rstrip()
    + "\n" + css3.rstrip()
    + "\n</style>\n"
    + '<script src="qrc:///qtwebchannel/qwebchannel.js"></script>\n'
    + "</head>\n<body>\n"
    + body.rstrip()
    + "\n<script>\n"
    + js.rstrip()
    + "\n</script>\n</body>\n</html>\n"
)

OUT.write_text(html, encoding="utf-8", newline="")
print(f"written {OUT}  {len(html)} chars")

# sanity: tag balance + no leftover markers
import re
for tag in ("div", "aside", "main", "style", "script", "body", "html", "select", "button"):
    o = len(re.findall(r"<" + tag + r"[ >]", html))
    c = len(re.findall(r"</" + tag + r">", html))
    flag = "" if o == c else "   <-- MISMATCH"
    print(f"  {tag:8s} open={o:3d} close={c:3d}{flag}")
