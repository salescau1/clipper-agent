"""Generator 10 Frame Baru dengan 5 Gaya Visual Berbeda untuk Clipper Agent.

Gaya:
1. Minimalist Glass / Card (Dark Glass & Clean White)
2. Cyberpunk HUD (Neon Cyan & Amber Circuit)
3. Retro OS Window (Win98 Classic & Vaporwave Pink)
4. Cinematic Film Reel (35mm Film Strip & Matte Cinema Gold)
5. Pop Art Comic (Manga Dot & Comic Yellow)
"""
import json
import math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
FRAMES_DIR = ROOT / "assets" / "frames"
W, H = 1080, 1920

def save_frame_entry(fid, name, category, tags, img, win_top, win_bottom, sub_y=None, hl_y=55):
    d = FRAMES_DIR / fid
    d.mkdir(parents=True, exist_ok=True)
    
    png_path = d / "frame.png"
    img.save(png_path, "PNG")
    
    thumb = img.copy()
    thumb.thumbnail((240, 427))
    bg = Image.new("RGB", thumb.size, (15, 18, 26))
    bg.paste(thumb, (0, 0), thumb)
    bg.save(d / "thumbnail.png", "PNG")
    
    if sub_y is None:
        sub_y = min(H - 120, win_bottom - 180)
        
    meta = {
        "id": fid,
        "name": name,
        "category": category,
        "tags": tags,
        "ratio": "9:16",
        "canvas": {"w": W, "h": H},
        "video_slot": {
            "scale": 1.0,
            "y": (win_top + win_bottom) // 2,
            "radius": 0,
            "aspect": "16/9"
        },
        "subtitle_slot": {"y": sub_y, "size": 80},
        "headline_slot": {"x": 45, "y": hl_y, "size": 86},
        "recommended_subtitle": {
            "animation": "word",
            "color": "#FFFFFF",
            "active_color": "#FFA500"
        },
        "window": {"top": int(win_top), "bottom": int(win_bottom)}
    }
    (d / "frame.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Created frame: {fid} ({name}) -> window {win_top}..{win_bottom}")

# ==============================================================================
# 1. MINIMALIST CARD (Dark Glass & Clean White)
# ==============================================================================
def make_minimalist_dark():
    # Dark modern matte card with rounded cut and subtle gradient glow
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    win_top, win_bottom = 540, 1380
    
    # Top card (0..540)
    top_card = Image.new("RGBA", (W, win_top), (18, 20, 28, 255))
    t_draw = ImageDraw.Draw(top_card)
    # subtle gradient line at bottom
    t_draw.line([(0, win_top-3), (W, win_top-3)], fill=(40, 48, 68, 255), width=3)
    t_draw.line([(0, win_top-1), (W, win_top-1)], fill=(0, 200, 255, 180), width=2)
    img.paste(top_card, (0, 0))
    
    # Bottom card (1380..1920)
    bot_card = Image.new("RGBA", (W, H - win_bottom), (18, 20, 28, 255))
    b_draw = ImageDraw.Draw(bot_card)
    b_draw.line([(0, 1), (W, 1)], fill=(0, 200, 255, 180), width=2)
    b_draw.line([(0, 3), (W, 3)], fill=(40, 48, 68, 255), width=3)
    img.paste(bot_card, (0, win_bottom))
    
    return img, win_top, win_bottom

def make_minimalist_white():
    # Clean studio white/platinum card with soft dark drop shadow
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    win_top, win_bottom = 520, 1400
    
    # Top card
    top_card = Image.new("RGBA", (W, win_top), (245, 246, 250, 255))
    t_draw = ImageDraw.Draw(top_card)
    t_draw.line([(0, win_top-4), (W, win_top-4)], fill=(210, 215, 225, 255), width=4)
    img.paste(top_card, (0, 0))
    
    # Bottom card
    bot_card = Image.new("RGBA", (W, H - win_bottom), (245, 246, 250, 255))
    b_draw = ImageDraw.Draw(bot_card)
    b_draw.line([(0, 2), (W, 2)], fill=(210, 215, 225, 255), width=4)
    img.paste(bot_card, (0, win_bottom))
    
    return img, win_top, win_bottom

# ==============================================================================
# 2. CYBERPUNK HUD (Neon Cyan & Amber Circuit)
# ==============================================================================
def make_cyberpunk_cyan():
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    win_top, win_bottom = 540, 1380
    
    # Top tech plate
    top_plate = Image.new("RGBA", (W, win_top), (10, 14, 22, 255))
    td = ImageDraw.Draw(top_plate)
    # HUD grid / lines
    for x in range(0, W, 80):
        td.line([(x, 0), (x, win_top)], fill=(18, 28, 45, 255), width=1)
    # Tech chamfer bracket at bottom
    td.polygon([(0, win_top), (80, win_top-40), (W-80, win_top-40), (W, win_top), (W, win_top-6), (0, win_top-6)], fill=(0, 240, 255, 255))
    # Corner HUD accents
    td.rectangle([40, 40, 160, 46], fill=(0, 240, 255, 255))
    td.rectangle([W-160, 40, W-40, 46], fill=(0, 240, 255, 255))
    img.paste(top_plate, (0, 0))
    
    # Bottom plate
    bot_plate = Image.new("RGBA", (W, H - win_bottom), (10, 14, 22, 255))
    bd = ImageDraw.Draw(bot_plate)
    for x in range(0, W, 80):
        bd.line([(x, 0), (x, H - win_bottom)], fill=(18, 28, 45, 255), width=1)
    bd.polygon([(0, 0), (80, 40), (W-80, 40), (W, 0), (W, 6), (0, 6)], fill=(0, 240, 255, 255))
    img.paste(bot_plate, (0, win_bottom))
    
    return img, win_top, win_bottom

def make_cyberpunk_amber():
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    win_top, win_bottom = 540, 1380
    
    # Top plate dark carbon
    top_plate = Image.new("RGBA", (W, win_top), (18, 14, 10, 255))
    td = ImageDraw.Draw(top_plate)
    # Neon Amber borders
    td.line([(0, win_top-8), (W, win_top-8)], fill=(255, 170, 0, 255), width=6)
    td.line([(0, win_top-18), (W, win_top-18)], fill=(120, 60, 0, 255), width=2)
    # Warning tech stripes
    for i in range(0, 300, 30):
        td.polygon([(40 + i, 60), (60 + i, 60), (45 + i, 80), (25 + i, 80)], fill=(255, 170, 0, 200))
    img.paste(top_plate, (0, 0))
    
    # Bottom plate
    bot_plate = Image.new("RGBA", (W, H - win_bottom), (18, 14, 10, 255))
    bd = ImageDraw.Draw(bot_plate)
    bd.line([(0, 8), (W, 8)], fill=(255, 170, 0, 255), width=6)
    bd.line([(0, 18), (W, 18)], fill=(120, 60, 0, 255), width=2)
    img.paste(bot_plate, (0, win_bottom))
    
    return img, win_top, win_bottom

# ==============================================================================
# 3. RETRO OS WINDOW (Win98 Classic & Vaporwave Pink)
# ==============================================================================
def make_retro_win98():
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    win_top, win_bottom = 500, 1420
    
    # Top window header
    top_part = Image.new("RGBA", (W, win_top), (192, 192, 192, 255))
    td = ImageDraw.Draw(top_part)
    # Classic blue titlebar
    td.rectangle([16, 60, W-16, 140], fill=(0, 0, 128, 255))
    # 3 button controls on right
    td.rectangle([W-130, 75, W-100, 125], fill=(192, 192, 192, 255), outline=(255, 255, 255, 255))
    td.rectangle([W-90, 75, W-60, 125], fill=(192, 192, 192, 255), outline=(255, 255, 255, 255))
    td.rectangle([W-50, 75, W-20, 125], fill=(192, 192, 192, 255), outline=(255, 255, 255, 255))
    # Bevel lines
    td.line([(0, win_top-6), (W, win_top-6)], fill=(128, 128, 128, 255), width=4)
    td.line([(0, win_top-2), (W, win_top-2)], fill=(255, 255, 255, 255), width=2)
    img.paste(top_part, (0, 0))
    
    # Bottom window footer
    bot_part = Image.new("RGBA", (W, H - win_bottom), (192, 192, 192, 255))
    bd = ImageDraw.Draw(bot_part)
    bd.line([(0, 2), (W, 2)], fill=(255, 255, 255, 255), width=2)
    bd.line([(0, 6), (W, 6)], fill=(128, 128, 128, 255), width=4)
    # Status bar box
    bd.rectangle([16, 40, W-16, 100], fill=(180, 180, 180, 255), outline=(128, 128, 128, 255))
    img.paste(bot_part, (0, win_bottom))
    
    return img, win_top, win_bottom

def make_retro_vaporwave():
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    win_top, win_bottom = 510, 1410
    
    # Top pastel vaporwave header
    top_part = Image.new("RGBA", (W, win_top), (255, 182, 193, 255))
    td = ImageDraw.Draw(top_part)
    # Gradient cyan titlebar
    td.rectangle([16, 60, W-16, 140], fill=(0, 210, 220, 255))
    # Aesthetic checkerboard strip
    for i in range(0, W, 30):
        td.rectangle([i, win_top-25, i+15, win_top], fill=(138, 43, 226, 255))
    img.paste(top_part, (0, 0))
    
    # Bottom pastel footer
    bot_part = Image.new("RGBA", (W, H - win_bottom), (255, 182, 193, 255))
    bd = ImageDraw.Draw(bot_part)
    for i in range(0, W, 30):
        bd.rectangle([i, 0, i+15, 25], fill=(138, 43, 226, 255))
    img.paste(bot_part, (0, win_bottom))
    
    return img, win_top, win_bottom

# ==============================================================================
# 4. CINEMATIC FILM REEL (35mm Film Strip & Matte Cinema Gold)
# ==============================================================================
def make_cinema_film35():
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    win_top, win_bottom = 540, 1380
    
    # Black film border top
    top_part = Image.new("RGBA", (W, win_top), (12, 12, 14, 255))
    td = ImageDraw.Draw(top_part)
    # Sprocket holes along left and right edge
    for y in range(40, win_top - 40, 70):
        td.rounded_rectangle([30, y, 75, y + 45], radius=6, fill=(240, 240, 240, 220))
        td.rounded_rectangle([W - 75, y, W - 30, y + 45], radius=6, fill=(240, 240, 240, 220))
    # Red film frame index mark
    td.text((100, win_top - 60), "▶ KODAK 35mm SAFETY FILM", fill=(220, 60, 40, 255))
    img.paste(top_part, (0, 0))
    
    # Black film border bottom
    bot_part = Image.new("RGBA", (W, H - win_bottom), (12, 12, 14, 255))
    bd = ImageDraw.Draw(bot_part)
    for y in range(40, (H - win_bottom) - 40, 70):
        bd.rounded_rectangle([30, y, 75, y + 45], radius=6, fill=(240, 240, 240, 220))
        bd.rounded_rectangle([W - 75, y, W - 30, y + 45], radius=6, fill=(240, 240, 240, 220))
    bd.text((100, 30), "FRAME 04 • 24 FPS", fill=(200, 200, 200, 200))
    img.paste(bot_part, (0, win_bottom))
    
    return img, win_top, win_bottom

def make_cinema_gold():
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    win_top, win_bottom = 540, 1380
    
    # Deep matte charcoal top with gold hairline
    top_part = Image.new("RGBA", (W, win_top), (18, 18, 20, 255))
    td = ImageDraw.Draw(top_part)
    # Elegant double gold line
    td.line([(80, win_top-12), (W-80, win_top-12)], fill=(212, 175, 55, 255), width=3)
    td.line([(140, win_top-6), (W-140, win_top-6)], fill=(212, 175, 55, 180), width=1)
    img.paste(top_part, (0, 0))
    
    # Bottom part
    bot_part = Image.new("RGBA", (W, H - win_bottom), (18, 18, 20, 255))
    bd = ImageDraw.Draw(bot_part)
    bd.line([(140, 6), (W-140, 6)], fill=(212, 175, 55, 180), width=1)
    bd.line([(80, 12), (W-80, 12)], fill=(212, 175, 55, 255), width=3)
    img.paste(bot_part, (0, win_bottom))
    
    return img, win_top, win_bottom

# ==============================================================================
# 5. POP ART / COMIC (Manga Dot & Comic Yellow)
# ==============================================================================
def make_comic_yellow():
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    win_top, win_bottom = 520, 1400
    
    # Bold comic yellow top
    top_part = Image.new("RGBA", (W, win_top), (255, 221, 0, 255))
    td = ImageDraw.Draw(top_part)
    # Halftone dots pattern
    for y in range(20, win_top - 40, 32):
        for x in range(20, W, 32):
            td.ellipse([x, y, x+8, y+8], fill=(230, 190, 0, 255))
    # Heavy black comic border with jagged splash
    td.line([(0, win_top-8), (W, win_top-8)], fill=(0, 0, 0, 255), width=16)
    img.paste(top_part, (0, 0))
    
    # Comic yellow bottom
    bot_part = Image.new("RGBA", (W, H - win_bottom), (255, 221, 0, 255))
    bd = ImageDraw.Draw(bot_part)
    for y in range(40, (H - win_bottom) - 20, 32):
        for x in range(20, W, 32):
            bd.ellipse([x, y, x+8, y+8], fill=(230, 190, 0, 255))
    bd.line([(0, 8), (W, 8)], fill=(0, 0, 0, 255), width=16)
    img.paste(bot_part, (0, win_bottom))
    
    return img, win_top, win_bottom

def make_comic_manga():
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    win_top, win_bottom = 520, 1400
    
    # Manga screentone top
    top_part = Image.new("RGBA", (W, win_top), (250, 250, 250, 255))
    td = ImageDraw.Draw(top_part)
    # Diagonal speed lines
    for i in range(-win_top, W, 25):
        td.line([(i, 0), (i + win_top, win_top)], fill=(210, 210, 210, 255), width=3)
    # Heavy ink border
    td.line([(0, win_top-6), (W, win_top-6)], fill=(20, 20, 20, 255), width=12)
    img.paste(top_part, (0, 0))
    
    # Manga bottom
    bot_part = Image.new("RGBA", (W, H - win_bottom), (250, 250, 250, 255))
    bd = ImageDraw.Draw(bot_part)
    for i in range(- (H-win_bottom), W, 25):
        bd.line([(i, 0), (i + (H-win_bottom), H-win_bottom)], fill=(210, 210, 210, 255), width=3)
    bd.line([(0, 6), (W, 6)], fill=(20, 20, 20, 255), width=12)
    img.paste(bot_part, (0, win_bottom))
    
    return img, win_top, win_bottom

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================
def main():
    creators = [
        ("glass-dark", "Dark Obsidian Glass", "minimal", ["dark", "modern", "glass"], make_minimalist_dark),
        ("card-white", "Clean White Card", "minimal", ["white", "clean", "minimal"], make_minimalist_white),
        ("cyber-cyan", "Neon Cyan HUD", "tech", ["cyberpunk", "neon", "hud"], make_cyberpunk_cyan),
        ("circuit-amber", "Amber Circuit Tech", "tech", ["cyberpunk", "amber", "tech"], make_cyberpunk_amber),
        ("win98-classic", "Classic Win98 Retro", "retro", ["retro", "win98", "y2k"], make_retro_win98),
        ("vapor-pink", "Vaporwave Pastel", "retro", ["vaporwave", "pink", "aesthetic"], make_retro_vaporwave),
        ("film-35mm", "Vintage 35mm Film", "cinema", ["film", "vintage", "cinema"], make_cinema_film35),
        ("cinema-gold", "Cinema Matte Gold", "cinema", ["cinema", "luxury", "gold"], make_cinema_gold),
        ("comic-yellow", "Pop-Art Yellow", "comic", ["comic", "popart", "vibrant"], make_comic_yellow),
        ("manga-screentone", "Manga Monochrome", "comic", ["manga", "anime", "screentone"], make_comic_manga),
    ]
    
    for fid, name, cat, tags, fn in creators:
        img, win_top, win_bottom = fn()
        save_frame_entry(fid, name, cat, tags, img, win_top, win_bottom)
        
    print(f"\nAll 10 frames successfully generated into {FRAMES_DIR}")

if __name__ == "__main__":
    main()
