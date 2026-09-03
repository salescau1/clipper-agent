import os
import glob
import math
import random
from PIL import Image, ImageDraw, ImageFilter

OUTPUT_DIR = r"C:\Clipper Agent\clipper\sampleframe"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Delete existing PNGs
for f in glob.glob(os.path.join(OUTPUT_DIR, "*.png")):
    try:
        os.remove(f)
    except Exception:
        pass

W, H = 1080, 1920

def new_canvas():
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))

# -------------------------------------------------------------
# 1. DARK CHARCOAL TORN PAPER (Kertas Robek Gelap / Burnt Craft)
# -------------------------------------------------------------
def make_dark_torn_paper():
    base = new_canvas()
    top_limit = 530
    bot_limit = 1390
    
    # Dark textured paper (Charcoal / Deep Slate)
    paper = Image.new("RGBA", (W, H), (22, 24, 28, 255))
    
    # Organic paper noise/grain
    random.seed(101)
    for _ in range(45000):
        gx = random.randint(0, W - 1)
        gy = random.randint(0, H - 1)
        noise = random.randint(-12, 12)
        c = max(10, min(45, 24 + noise))
        paper.putpixel((gx, gy), (c, c, c + 2, 255))
        
    mask = Image.new("L", (W, H), 0)
    draw_m = ImageDraw.Draw(mask)
    
    # Top paper polygon (jagged torn edge)
    top_poly = [(0, 0), (W, 0)]
    curr_y = top_limit
    for x in range(W, -8, -8):
        wave = math.sin(x * 0.014) * 22 + math.cos(x * 0.035) * 8
        micro = random.uniform(-4, 4)
        top_poly.append((x, int(curr_y + wave + micro)))
    draw_m.polygon(top_poly, fill=255)
    
    # Bottom paper polygon
    bot_poly = [(0, H), (W, H)]
    curr_y_b = bot_limit
    for x in range(W, -8, -8):
        wave = math.sin(x * 0.016 + 1.2) * 25 + math.cos(x * 0.028) * 10
        micro = random.uniform(-4, 4)
        bot_poly.append((x, int(curr_y_b + wave + micro)))
    draw_m.polygon(bot_poly, fill=255)
    
    # Deep shadow behind torn edges
    shadow_mask = mask.filter(ImageFilter.GaussianBlur(radius=20))
    shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 220))
    base.paste(shadow_layer, (0, 10), shadow_mask)
    
    # Torn edge subtle white/grey fiber highlight (thin rim)
    edge_mask = mask.filter(ImageFilter.GaussianBlur(radius=1.5))
    edge_highlight = Image.new("RGBA", (W, H), (80, 85, 95, 180))
    base.paste(edge_highlight, (0, 0), edge_mask)
    
    # Paste main dark paper
    base.paste(paper, (0, 0), mask)
    
    # Dark textured tape accents
    tape = Image.new("RGBA", (220, 65), (35, 38, 45, 210))
    t_draw = ImageDraw.Draw(tape)
    t_draw.line([(0, 0), (220, 0)], fill=(70, 75, 85, 140), width=2)
    tape_rot1 = tape.rotate(12, expand=True, resample=Image.BICUBIC)
    base.paste(tape_rot1, (50, 470), tape_rot1)
    tape_rot2 = tape.rotate(-15, expand=True, resample=Image.BICUBIC)
    base.paste(tape_rot2, (W - 270, 1350), tape_rot2)

    out_path = os.path.join(OUTPUT_DIR, "01_dark_torn_charcoal.png")
    base.save(out_path)
    print("Generated:", out_path)

# -------------------------------------------------------------
# 2. MIDNIGHT BOTANICAL (Dedaunan Gelap / Deep Forest Slate)
# -------------------------------------------------------------
def make_dark_botanical():
    base = new_canvas()
    
    # Deep obsidian / matte dark moss cards
    top_box = [36, 36, W - 36, 490]
    bot_box = [36, 1430, W - 36, H - 36]
    
    # Drop shadow
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow)
    s_draw.rounded_rectangle(top_box, radius=28, fill=(0, 0, 0, 230))
    s_draw.rounded_rectangle(bot_box, radius=28, fill=(0, 0, 0, 230))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    base.paste(shadow, (0, 12), shadow)
    
    # Dark Slate plates (very dark grey-green tone)
    plate = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    p_draw = ImageDraw.Draw(plate)
    dark_slate = (15, 20, 18, 245)
    border_muted = (42, 60, 50, 180)
    p_draw.rounded_rectangle(top_box, radius=28, fill=dark_slate, outline=border_muted, width=2)
    p_draw.rounded_rectangle(bot_box, radius=28, fill=dark_slate, outline=border_muted, width=2)
    
    # Add subtle dark foliage silhouettes (shadow leaves)
    def draw_dark_leaf(cx, cy, length, angle, color):
        leaf_img = Image.new("RGBA", (length * 2, length * 2), (0, 0, 0, 0))
        ld = ImageDraw.Draw(leaf_img)
        pts = [(length, length - length//2), (length + length//3, length), (length, length + length//2), (length - length//3, length)]
        ld.polygon(pts, fill=color)
        ld.line([(length, length - length//2), (length, length + length//2)], fill=(min(255, color[0]+15), min(255, color[1]+20), min(255, color[2]+15), 180), width=1)
        rot = leaf_img.rotate(angle, expand=True, resample=Image.BICUBIC)
        plate.paste(rot, (cx - rot.width//2, cy - rot.height//2), rot)
        
    # Dark moody muted leaves (deep forest green tones, not bright)
    leaf_c1 = (25, 42, 32, 220)
    leaf_c2 = (18, 30, 24, 200)
    draw_dark_leaf(75, 80, 110, -40, leaf_c1)
    draw_dark_leaf(120, 130, 90, 15, leaf_c2)
    draw_dark_leaf(W - 80, 90, 120, 45, leaf_c1)
    draw_dark_leaf(80, H - 100, 130, 35, leaf_c1)
    draw_dark_leaf(W - 90, H - 90, 120, -45, leaf_c2)
    
    # Thin elegant muted border around video cutout (y=500 to 1420)
    p_draw.rounded_rectangle([32, 498, W - 32, 1422], radius=20, outline=(35, 52, 42, 160), width=2)
    
    base.paste(plate, (0, 0), plate)
    out_path = os.path.join(OUTPUT_DIR, "02_midnight_botanical.png")
    base.save(out_path)
    print("Generated:", out_path)

# -------------------------------------------------------------
# 3. STEALTH FUTURISTIC HUD (Dark Titanium / Subtle Cyan Glow)
# -------------------------------------------------------------
def make_stealth_futuristic():
    base = new_canvas()
    
    top_box = [30, 30, W - 30, 500]
    bot_box = [30, 1420, W - 30, H - 30]
    
    # Deep pitch-black glass plates
    glass = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(glass)
    dark_hud_bg = (10, 12, 16, 248)
    subtle_border = (28, 40, 52, 200)
    g_draw.rounded_rectangle(top_box, radius=16, fill=dark_hud_bg, outline=subtle_border, width=2)
    g_draw.rounded_rectangle(bot_box, radius=16, fill=dark_hud_bg, outline=subtle_border, width=2)
    
    # Futuristic HUD brackets & tech accents (deep muted cyan & amber, not blinding)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gl_draw = ImageDraw.Draw(glow)
    
    accent_cyan = (0, 180, 210, 230)
    accent_dark = (0, 100, 130, 150)
    
    win_l, win_t, win_r, win_b = 30, 510, W - 30, 1410
    blen = 45
    # Corner tactical brackets
    for (x, y, dx, dy) in [
        (win_l, win_t, blen, 0), (win_l, win_t, 0, blen),
        (win_r, win_t, -blen, 0), (win_r, win_t, 0, blen),
        (win_l, win_b, blen, 0), (win_l, win_b, 0, -blen),
        (win_r, win_b, -blen, 0), (win_r, win_b, 0, -blen)
    ]:
        gl_draw.line([(x, y), (x + dx, y + dy)], fill=accent_cyan, width=4)
        
    # Top card subtle tech grid & crosshairs
    for gx in range(60, W - 60, 48):
        for gy in range(60, 160, 48):
            gl_draw.rectangle([gx, gy, gx+1, gy+1], fill=accent_dark)
            
    gl_draw.line([(W - 120, 90), (W - 60, 90)], fill=accent_cyan, width=2)
    gl_draw.line([(W - 90, 60), (W - 90, 120)], fill=accent_cyan, width=2)
    gl_draw.arc([W - 110, 70, W - 70, 110], 0, 360, fill=accent_cyan, width=2)
    
    # Bottom card subtle minimalist audio bars (dark tech aesthetic)
    bar_x = 70
    random.seed(99)
    for _ in range(26):
        b_h = random.randint(10, 45)
        gl_draw.rounded_rectangle([bar_x, H - 75 - b_h, bar_x + 16, H - 75], radius=3, fill=(15, 75, 95, 200))
        gl_draw.rounded_rectangle([bar_x, H - 75 - b_h - 6, bar_x + 16, H - 75 - b_h - 3], radius=1, fill=accent_cyan)
        bar_x += 36
        
    glow_soft = glow.filter(ImageFilter.GaussianBlur(6))
    
    base.paste(glass, (0, 0), glass)
    base.paste(glow_soft, (0, 0), glow_soft)
    base.paste(glow, (0, 0), glow)
    
    out_path = os.path.join(OUTPUT_DIR, "03_stealth_futuristic_hud.png")
    base.save(out_path)
    print("Generated:", out_path)

# -------------------------------------------------------------
# 4. MATTE CARBON & SMOKED BRONZE (Dark Luxury Minimalist)
# -------------------------------------------------------------
def make_matte_carbon_bronze():
    base = new_canvas()
    
    plate = Image.new("RGBA", (W, H), (14, 14, 17, 250))
    
    # Fine carbon/slate grain
    random.seed(88)
    for _ in range(50000):
        nx = random.randint(0, W - 1)
        ny = random.randint(0, H - 1)
        val = random.randint(8, 20)
        plate.putpixel((nx, ny), (val, val, val + 2, 255))
        
    mask = Image.new("L", (W, H), 255)
    m_draw = ImageDraw.Draw(mask)
    # Video cutout hole
    m_draw.rounded_rectangle([34, 510, W - 34, 1410], radius=24, fill=0)
    
    # Smoked antique bronze / dark gold rim
    border = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    b_draw = ImageDraw.Draw(border)
    b_draw.rounded_rectangle([34, 510, W - 34, 1410], radius=24, outline=(160, 125, 60, 220), width=3)
    b_draw.rounded_rectangle([40, 516, W - 40, 1404], radius=18, outline=(80, 60, 30, 140), width=1)
    
    # Soft inner drop shadow around window
    shadow_hole = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sh_draw = ImageDraw.Draw(shadow_hole)
    sh_draw.rounded_rectangle([28, 504, W - 28, 1416], radius=24, fill=(0, 0, 0, 240))
    shadow_hole = shadow_hole.filter(ImageFilter.GaussianBlur(16))
    
    base.paste(shadow_hole, (0, 0), shadow_hole)
    base.paste(plate, (0, 0), mask)
    base.paste(border, (0, 0), border)
    
    out_path = os.path.join(OUTPUT_DIR, "04_matte_carbon_bronze.png")
    base.save(out_path)
    print("Generated:", out_path)

if __name__ == "__main__":
    make_dark_torn_paper()
    make_dark_botanical()
    make_stealth_futuristic()
    make_matte_carbon_bronze()
    print("All dark sample frames generated successfully!")
