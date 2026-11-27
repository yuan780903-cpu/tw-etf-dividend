#!/usr/bin/env python3
"""12 個月節日主題 logo:以原柴犬博士 logo.svg 為底,換背景色、帽子、手上道具、背景裝飾、衣服顏色。
用法: gen_logos.py <logo.svg> <輸出資料夾>"""
import sys, os, math, random
src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
B = open(src, encoding="utf-8").read()

def cut(s, a, b):
    i = s.index(a); j = s.index(b, i); return s[:i], s[i:j], s[j:]

MORTAR = cut(B, "    <!-- 博士帽 -->", "    <!-- 眼睛")[1]
GOLD = 'url(#gd)'

# ---------- 小零件 ----------
def lantern(x, y, s=1, c="#E23B2E", glow=True):
    return f'''<g transform="translate({x} {y}) scale({s})">{'<circle r="34" fill="#FFB347" opacity=".25"/>' if glow else ''}
  <path d="M0 -30 L0 -22" stroke="{GOLD}" stroke-width="3"/><rect x="-9" y="-24" width="18" height="6" rx="2" fill="{GOLD}"/>
  <ellipse rx="22" ry="20" fill="{c}"/><path d="M-11 -18 C-16 -6 -16 6 -11 18 M11 -18 C16 -6 16 6 11 18 M0 -20 L0 20" stroke="#B0201A" stroke-width="2" fill="none"/>
  <rect x="-9" y="18" width="18" height="6" rx="2" fill="{GOLD}"/><path d="M-4 24 L-5 36 M0 24 L0 38 M4 24 L5 36" stroke="#F2C14E" stroke-width="2"/></g>'''

def burst(x, y, r, c, n=12, w=3):
    L = []
    for i in range(n):
        a = i / n * 2 * math.pi
        L.append(f'<path d="M{x+math.cos(a)*r*.35:.1f} {y+math.sin(a)*r*.35:.1f} L{x+math.cos(a)*r:.1f} {y+math.sin(a)*r:.1f}" stroke="{c}" stroke-width="{w}" stroke-linecap="round"/>')
        L.append(f'<circle cx="{x+math.cos(a)*r*1.12:.1f}" cy="{y+math.sin(a)*r*1.12:.1f}" r="{w*.8:.1f}" fill="{c}"/>')
    return "".join(L)

def star(x, y, r, c, op=1):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5; rr = r if i % 2 == 0 else r * .45
        pts.append(f"{x+math.cos(a)*rr:.1f},{y+math.sin(a)*rr:.1f}")
    return f'<polygon points="{" ".join(pts)}" fill="{c}" opacity="{op}"/>'

def sparkle(x, y, r, c, op=1):
    return f'<path d="M{x} {y-r} Q{x} {y} {x+r} {y} Q{x} {y} {x} {y+r} Q{x} {y} {x-r} {y} Q{x} {y} {x} {y-r} Z" fill="{c}" opacity="{op}"/>'

def heart(x, y, s, c, op=1, rot=0):
    return f'<path transform="translate({x} {y}) rotate({rot}) scale({s})" d="M0 6 C-10 -4 -20 2 -14 12 L0 26 L14 12 C20 2 10 -4 0 6 Z" fill="{c}" opacity="{op}"/>'

def petal(x, y, s, c, rot, op=1):
    return f'<path transform="translate({x} {y}) rotate({rot}) scale({s})" d="M0 -14 C9 -10 10 6 0 14 C-10 6 -9 -10 0 -14 Z M0 -14 L-3 -9 L0 -11 L3 -9 Z" fill="{c}" opacity="{op}"/>'

def sakura(x, y, s, op=1):
    p = "".join(f'<ellipse cx="0" cy="-9" rx="6" ry="9" fill="#FFC4D6" transform="rotate({i*72})"/>' for i in range(5))
    return f'<g transform="translate({x} {y}) scale({s})" opacity="{op}">{p}<circle r="4" fill="#F27BA0"/></g>'

def maple(x, y, s, c, rot, op=1):
    d = "M0 -22 L5 -10 L14 -14 L11 -3 L22 -2 L13 6 L17 14 L5 11 L2 22 L0 14 L-2 22 L-5 11 L-17 14 L-13 6 L-22 -2 L-11 -3 L-14 -14 L-5 -10 Z"
    return f'<path transform="translate({x} {y}) rotate({rot}) scale({s})" d="{d}" fill="{c}" opacity="{op}"/>'

def snow(x, y, r, op=1):
    L = []
    for i in range(6):
        a = i * math.pi / 3; ex, ey = x + math.cos(a) * r, y + math.sin(a) * r
        L.append(f'M{x} {y} L{ex:.1f} {ey:.1f}')
        bx, by = x + math.cos(a) * r * .6, y + math.sin(a) * r * .6
        for d in (-.6, .6):
            L.append(f'M{bx:.1f} {by:.1f} L{bx+math.cos(a+d)*r*.3:.1f} {by+math.sin(a+d)*r*.3:.1f}')
    return f'<path d="{" ".join(L)}" stroke="#fff" stroke-width="{max(1.6, r/8):.1f}" stroke-linecap="round" opacity="{op}" fill="none"/>'

def bat(x, y, s, op=1):
    return f'<path transform="translate({x} {y}) scale({s})" d="M0 0 C-6 -8 -14 -8 -22 -4 C-18 0 -18 4 -20 8 C-14 4 -8 6 -4 10 C-2 6 2 6 4 10 C8 6 14 4 20 8 C18 4 18 0 22 -4 C14 -8 6 -8 0 0 Z M-3 -2 L-5 -8 L-1 -4 Z M3 -2 L5 -8 L1 -4 Z" fill="#1A1028" opacity="{op}"/>'

def wave(y, c, op):
    d = f"M0 {y}" + "".join(f" q 32 -22 64 0 t 64 0" for _ in range(5)) + f" L512 512 L0 512 Z"
    return f'<path d="{d}" fill="{c}" opacity="{op}"/>'

random.seed(7)
# ---------- 帽子 ----------
SANTA = '''    <!-- 聖誕帽 -->
    <path d="M162 156 C176 92 238 66 300 74 C352 82 384 110 404 150 C380 130 352 122 330 132 C340 140 344 148 346 156 Z" fill="#D7263D"/>
    <path d="M300 74 C352 82 384 110 404 150 C388 140 372 136 356 138 C340 112 322 92 300 74 Z" fill="#A81C2E" opacity=".6"/>
    <circle cx="404" cy="152" r="19" fill="#FFFFFF"/><circle cx="398" cy="146" r="7" fill="#EEF3FF"/>
    <path d="M150 164 C150 140 210 132 256 132 C302 132 362 140 362 164 C362 184 302 182 256 182 C210 182 150 184 150 164 Z" fill="#FFFFFF"/>
    <path d="M168 160 C190 152 230 150 256 150 C282 150 322 152 344 160" stroke="#E6ECF5" stroke-width="5" fill="none" stroke-linecap="round"/>
'''
WITCH = '''    <!-- 巫師帽 -->
    <ellipse cx="256" cy="150" rx="138" ry="26" fill="#241436"/>
    <path d="M190 146 C204 110 222 60 262 30 C270 24 300 34 318 52 C300 50 288 58 282 74 C296 98 314 124 324 146 C292 158 220 158 190 146 Z" fill="#2E1A47"/>
    <path d="M194 136 C226 146 290 146 320 136 L324 148 C290 160 222 160 190 148 Z" fill="#F28C28"/>
    <rect x="243" y="132" width="26" height="22" rx="3" fill="none" stroke="url(#gd)" stroke-width="5"/>
    <ellipse cx="256" cy="148" rx="138" ry="26" fill="none" stroke="#3D2460" stroke-width="3"/>
'''
STRAW = '''    <!-- 草帽 -->
    <ellipse cx="256" cy="150" rx="148" ry="32" fill="#E9C46A"/>
    <ellipse cx="256" cy="146" rx="148" ry="28" fill="#F4D58D"/>
    <path d="M188 146 C188 96 220 78 256 78 C292 78 324 96 324 146 C296 156 216 156 188 146 Z" fill="#F4D58D"/>
    <path d="M190 128 C222 138 290 138 322 128 L324 146 C292 156 220 156 188 146 Z" fill="#E63946"/>
    <path d="M200 100 C230 92 282 92 312 100 M196 116 C230 108 282 108 316 116" stroke="#D9B25F" stroke-width="3" fill="none"/>
    <path d="M128 154 C180 170 332 170 384 154" stroke="#D9B25F" stroke-width="3" fill="none"/>
'''
SKULLCAP = '''    <!-- 瓜皮帽(春節) -->
    <path d="M178 150 C178 104 214 84 256 84 C298 84 334 104 334 150 C300 160 212 160 178 150 Z" fill="#B3121E"/>
    <path d="M256 84 L256 154 M216 92 L208 152 M296 92 L304 152" stroke="#8C0D16" stroke-width="3"/>
    <path d="M176 146 C212 158 300 158 336 146 L336 160 C300 172 212 172 176 160 Z" fill="url(#gd)"/>
    <circle cx="256" cy="80" r="11" fill="#D7263D" stroke="url(#gd)" stroke-width="4"/>
'''

# ---------- 道具(右下,原算盤位置) ----------
PAW = '<ellipse cx="-4" cy="46" rx="20" ry="16" fill="url(#fur)"/><ellipse cx="-6" cy="48" rx="10" ry="8" fill="#FFF3DE"/>'
def prop(inner, x=330, y=396, rot=-10):
    return f'    <!-- 道具 -->\n    <g transform="translate({x-22} {y-44}) rotate({rot}) scale(1.18)">{inner}{PAW}</g>\n'

P = {
 1: prop('''<path d="M10 70 L60 6 L84 30 Z" fill="#7B2FF7"/><path d="M22 54 L66 12 M34 62 L76 22" stroke="url(#gd)" stroke-width="5"/>
   <path d="M60 6 L84 30" stroke="#5A1FC0" stroke-width="6" stroke-linecap="round"/>''' + burst(84, 4, 34, "#FFD166", 10, 3) + sparkle(110, 34, 9, "#fff") + sparkle(64, -26, 7, "#FF8FAB") + '<circle cx="104" cy="-14" r="4" fill="#4CC9F0"/><rect x="40" y="-30" width="7" height="7" fill="#06D6A0" transform="rotate(20 40 -30)"/>', 330, 400),
 2: prop('''<rect x="6" y="-6" width="70" height="92" rx="8" fill="#D7263D" stroke="url(#gd)" stroke-width="4"/>
   <path d="M6 18 C26 34 56 34 76 18" stroke="url(#gd)" stroke-width="4" fill="none"/>
   <circle cx="41" cy="50" r="20" fill="url(#gd)"/><text x="41" y="58" text-anchor="middle" font-family="'Noto Serif TC','Songti TC','PMingLiU',serif" font-weight="900" font-size="24" fill="#B3121E">福</text>''', 336, 392, -12),
 3: prop('<path d="M10 40 L60 -40" stroke="#8B5A2B" stroke-width="6" stroke-linecap="round"/>' + lantern(70, -6, 1.25, "#F25C2E"), 330, 404),
 4: prop('''<path d="M14 40 L84 40 L76 86 L22 86 Z" fill="#B5651D"/><rect x="10" y="32" width="78" height="12" rx="4" fill="#C97B2E"/>
   <path d="M49 34 C49 14 48 0 50 -16" stroke="#2D8A4E" stroke-width="5" fill="none" stroke-linecap="round"/>
   <path d="M50 -4 C30 -10 20 -28 26 -36 C42 -32 52 -20 50 -4 Z" fill="#43AA5B"/><path d="M50 -14 C68 -24 84 -22 88 -12 C76 -2 60 -4 50 -14 Z" fill="#5CC46E"/>
   <circle cx="50" cy="-22" r="11" fill="url(#gd)"/><text x="50" y="-17" text-anchor="middle" font-family="Arial,sans-serif" font-weight="900" font-size="13" fill="#7A4A1E">$</text>''', 330, 400),
 5: prop('''<path d="M20 86 L44 30 L70 86 Z" fill="#FFF1F5" stroke="#F4A3BC" stroke-width="3"/>
   <path d="M44 34 L30 -2 M44 34 L46 -10 M44 34 L64 -2" stroke="#3E8E4F" stroke-width="4"/>
   <g fill="#F25C8A"><circle cx="28" cy="-6" r="15"/><circle cx="48" cy="-18" r="16"/><circle cx="68" cy="-6" r="15"/></g>
   <g fill="#FF9EBB"><circle cx="24" cy="-10" r="7"/><circle cx="44" cy="-22" r="7"/><circle cx="64" cy="-10" r="7"/></g>
   <path d="M30 60 C40 52 50 52 58 60 L44 70 Z" fill="#E63973"/>''', 332, 398),
 6: prop('''<path d="M6 70 L46 -8 L88 70 Z" fill="#3E8E4F"/><path d="M46 -8 L88 70 L60 70 Z" fill="#2F6E3B"/>
   <path d="M14 56 L80 56 M24 38 L70 38" stroke="#E9D8A6" stroke-width="5"/><path d="M46 -8 L46 70" stroke="#5FAE6E" stroke-width="2"/>
   <path d="M80 56 C96 60 100 70 94 78" stroke="#E9D8A6" stroke-width="4" fill="none"/>''', 330, 400),
 7: prop('''<path d="M0 30 A50 50 0 0 0 100 30 Z" fill="#2D8A4E"/><path d="M6 30 A44 44 0 0 0 94 30 Z" fill="#E9F5DB"/><path d="M12 30 A38 38 0 0 0 88 30 Z" fill="#EF476F"/>
   <g fill="#1B1B22"><ellipse cx="30" cy="44" rx="3" ry="5"/><ellipse cx="50" cy="52" rx="3" ry="5"/><ellipse cx="70" cy="44" rx="3" ry="5"/><ellipse cx="40" cy="38" rx="3" ry="5"/><ellipse cx="60" cy="38" rx="3" ry="5"/></g>''', 326, 380, -14),
 8: prop('''<path d="M14 -4 L80 -4 L74 40 C70 56 24 56 20 40 Z" fill="url(#gd)"/>
   <path d="M14 4 C-4 4 -4 30 18 32 M80 4 C98 4 98 30 76 32" stroke="url(#gd)" stroke-width="6" fill="none"/>
   <rect x="38" y="52" width="18" height="16" fill="url(#gd)"/><rect x="22" y="66" width="50" height="14" rx="3" fill="#14213D" stroke="url(#gd)" stroke-width="3"/>
   <text x="47" y="28" text-anchor="middle" font-family="Arial Black,Arial,sans-serif" font-weight="900" font-size="20" fill="#7A4A1E">No.1</text>''', 334, 398),
 9: prop('''<circle cx="48" cy="34" r="40" fill="#C98A3A"/><circle cx="48" cy="34" r="34" fill="#E0A85A"/>
   <circle cx="48" cy="34" r="22" fill="none" stroke="#B5762A" stroke-width="3"/>''' +
   "".join(f'<circle cx="{48+math.cos(i*math.pi/6)*34:.1f}" cy="{34+math.sin(i*math.pi/6)*34:.1f}" r="5" fill="#C98A3A"/>' for i in range(12)) +
   '<text x="48" y="43" text-anchor="middle" font-family="\'Noto Serif TC\',\'Songti TC\',serif" font-weight="900" font-size="24" fill="#8A5418">圓</text>', 330, 398),
 10: prop('''<ellipse cx="48" cy="40" rx="48" ry="40" fill="#F28C28"/><path d="M48 0 C30 0 28 80 48 80 M48 0 C66 0 68 80 48 80 M20 8 C6 24 6 58 20 74 M76 8 C90 24 90 58 76 74" stroke="#D96F12" stroke-width="3" fill="none"/>
   <path d="M46 2 C44 -8 48 -16 56 -18" stroke="#3E8E4F" stroke-width="6" fill="none" stroke-linecap="round"/>
   <path d="M24 30 L36 22 L38 36 Z M72 30 L60 22 L58 36 Z" fill="#2A1A0A"/><path d="M26 52 L34 48 L40 56 L48 48 L56 56 L62 48 L70 52 C62 66 34 66 26 52 Z" fill="#2A1A0A"/>
   <g fill="url(#gd)"><circle cx="34" cy="-6" r="9"/><circle cx="64" cy="-8" r="9"/></g>''', 328, 400),
 11: prop('''<path d="M12 8 L76 8 L70 78 C68 86 20 86 18 78 Z" fill="#FFF8EE" stroke="#C9A24E" stroke-width="3"/>
   <rect x="10" y="0" width="70" height="12" rx="4" fill="#7A4A1E"/><path d="M14 30 L74 30 L72 54 L16 54 Z" fill="#C0392B"/>
   <path d="M76 26 C96 26 96 54 74 56" stroke="#FFF8EE" stroke-width="7" fill="none"/>
   <path d="M30 -8 C24 -20 36 -26 30 -38 M48 -8 C42 -20 54 -26 48 -38" stroke="#fff" stroke-width="4" fill="none" stroke-linecap="round" opacity=".8"/>''' + maple(45, 42, .55, "#FFD166", 0), 334, 398),
 12: prop('''<rect x="4" y="16" width="88" height="64" rx="6" fill="#2A9D8F"/><rect x="0" y="6" width="96" height="18" rx="5" fill="#33B3A4"/>
   <rect x="40" y="6" width="16" height="74" fill="#E63946"/><path d="M48 6 C30 -14 14 -6 24 6 Z M48 6 C66 -14 82 -6 72 6 Z" fill="#E63946"/>
   <circle cx="48" cy="6" r="6" fill="url(#gd)"/>''', 330, 400),
}

# ---------- 背景裝飾 ----------
def D_new():
    return ('<circle cx="256" cy="520" r="230" fill="#FFB347" opacity=".22"/>' + burst(110, 120, 46, "#FFD166", 14, 3) +
            burst(400, 100, 38, "#FF8FAB", 12, 3) + burst(430, 250, 26, "#4CC9F0", 10, 2.5) + sparkle(80, 240, 10, "#fff", .8) + sparkle(160, 60, 7, "#fff", .7))
def D_cny():
    return (lantern(96, 110, 1.05) + lantern(416, 110, 1.05) + '<path d="M60 70 C150 96 362 96 452 70" stroke="url(#gd)" stroke-width="3" fill="none"/>' +
            "".join(f'<g opacity=".9"><ellipse cx="{x}" cy="{y}" rx="12" ry="8" fill="url(#gd)"/><rect x="{x-4}" y="{y-3}" width="8" height="6" fill="#B3121E"/></g>' for x, y in ((70, 260), (446, 270), (100, 330))))
def D_lantern():
    return ('<circle cx="400" cy="96" r="36" fill="#FFF3C4" opacity=".9"/>' + lantern(92, 150, .75, "#F25C2E") + lantern(150, 80, .55, "#FF8C42") +
            lantern(430, 230, .6, "#F25C2E") + lantern(70, 300, .5, "#FF8C42") + "".join(sparkle(x, y, 5, "#FFE8A3", .8) for x, y in ((200, 60), (330, 50), (460, 170), (50, 200))))
def D_spring():
    return "".join(sakura(x, y, s, .95) for x, y, s in ((84, 120, 1.3), (430, 104, 1.1), (450, 260, .9), (66, 280, .8), (150, 60, .7), (380, 40, .6))) + \
           "".join(petal(x, y, .7, "#FFC4D6", r, .85) for x, y, r in ((120, 200, 30), (400, 180, -40), (190, 90, 60), (330, 70, 10), (460, 330, 80)))
def D_mom():
    return "".join(heart(x, y, s, c, .85, r) for x, y, s, c, r in ((90, 110, 1.6, "#FF8FAB", -15), (410, 90, 1.3, "#FFC2D1", 12), (440, 240, 1, "#FF8FAB", 20),
            (70, 260, 1, "#FFC2D1", -20), (160, 50, .8, "#fff", 0), (360, 40, .7, "#fff", 0))) + "".join(petal(x, y, .6, "#FFD6E0", r, .8) for x, y, r in ((130, 180, 20), (390, 170, -30)))
def D_duanwu():
    boat = '''<g transform="translate(34 262) scale(.62)" opacity=".95"><path d="M0 30 C40 46 120 46 150 26 L156 16 C120 30 40 30 0 22 Z" fill="url(#gd)"/>
      <path d="M150 26 C160 10 172 6 178 12 C170 14 166 22 156 30 Z" fill="#D7263D"/><circle cx="170" cy="12" r="2.5" fill="#1B1B22"/>
      <g stroke="#14213D" stroke-width="3" stroke-linecap="round"><path d="M40 26 L30 8 M70 28 L60 10 M100 28 L90 10"/></g><path d="M0 22 C-8 14 -10 6 -4 0 C0 10 4 16 6 22 Z" fill="#D7263D"/></g>'''
    return wave(300, "#7FD1C7", .35) + wave(330, "#4FB3A9", .3) + boat + "".join(sparkle(x, y, 6, "#fff", .7) for x, y in ((420, 80), (380, 150), (460, 200), (90, 120), (120, 190)))
def D_summer():
    rays = "".join(f'<path d="M{96+math.cos(a)*56:.1f} {96+math.sin(a)*56:.1f} L{96+math.cos(a)*80:.1f} {96+math.sin(a)*80:.1f}" stroke="#FFD166" stroke-width="7" stroke-linecap="round"/>' for a in [i*math.pi/6 for i in range(12)])
    return ('<circle cx="96" cy="96" r="44" fill="#FFD166"/><circle cx="96" cy="96" r="34" fill="#FFE08A"/>' + rays +
            '<g fill="#fff" opacity=".85"><ellipse cx="410" cy="110" rx="46" ry="18"/><ellipse cx="386" cy="98" rx="26" ry="18"/><ellipse cx="430" cy="96" rx="22" ry="16"/></g>' + wave(318, "#7FDBFF", .3))
def D_dad():
    return "".join(star(x, y, r, c, o) for x, y, r, c, o in ((90, 110, 22, "#FFD166", .95), (420, 96, 18, "#FFD166", .9), (450, 220, 12, "#fff", .8),
            (70, 250, 12, "#fff", .7), (160, 56, 9, "#fff", .7), (360, 44, 8, "#FFD166", .8), (440, 320, 9, "#fff", .6)))
def D_moon():
    rabbit = '<g transform="translate(126 126)" fill="#E9D9A8" opacity=".55"><ellipse cx="0" cy="10" rx="16" ry="12"/><circle cx="12" cy="0" r="8"/><ellipse cx="12" cy="-14" rx="3" ry="10"/><ellipse cx="18" cy="-13" rx="3" ry="9"/></g>'
    return ('<circle cx="130" cy="128" r="70" fill="#FFF6D5" opacity=".18"/><circle cx="130" cy="128" r="54" fill="#FCEBB6"/><circle cx="114" cy="112" r="9" fill="#F2DC9C" opacity=".7"/><circle cx="150" cy="142" r="11" fill="#F2DC9C" opacity=".6"/>' +
            rabbit + '<g fill="#fff" opacity=".22"><ellipse cx="420" cy="150" rx="60" ry="14"/><ellipse cx="80" cy="220" rx="50" ry="10"/></g>' +
            "".join(sparkle(x, y, 6, "#FFE8A3", .8) for x, y in ((420, 80), (450, 230), (330, 50), (60, 300))))
def D_hallo():
    return ('<circle cx="404" cy="104" r="50" fill="#FFE08A" opacity=".95"/><circle cx="420" cy="92" r="40" fill="#3B1F5C" opacity=".0"/>' +
            bat(404, 104, 1.4, .95) + bat(96, 110, 1.6, .9) + bat(150, 64, 1, .8) + bat(450, 230, 1, .8) + bat(66, 250, .9, .7) +
            "".join(star(x, y, 5, "#FFD166", .8) for x, y in ((210, 50), (330, 40), (60, 180))))
def D_autumn():
    return "".join(maple(x, y, s, c, r, .95) for x, y, s, c, r in ((90, 110, 1.5, "#E85D04", -20), (420, 96, 1.3, "#F48C06", 25), (446, 240, 1, "#DC2F02", 10),
            (66, 260, .9, "#FAA307", -40), (160, 56, .8, "#FFBA08", 15), (360, 44, .7, "#E85D04", -10), (460, 330, .8, "#F48C06", 40)))
def D_xmas():
    return ("".join(snow(x, y, r, o) for x, y, r, o in ((92, 110, 22, .95), (420, 96, 18, .9), (450, 230, 12, .8), (66, 250, 12, .75), (160, 56, 9, .7), (360, 46, 9, .7), (440, 330, 8, .6))) +
            "".join(f'<circle cx="{random.randint(40,470)}" cy="{random.randint(30,360)}" r="{random.choice([2,2.5,3])}" fill="#fff" opacity=".7"/>' for _ in range(26)))

M = {  # 月: (名稱, 背景漸層, 衣服, 帽子, 裝飾)
 1:  ("元旦",   ("#1E2A78", "#0B1240"), None, MORTAR, D_new),
 2:  ("春節",   ("#C81D25", "#7A0C12"), ("#B3121E", "#8C0D16"), SKULLCAP, D_cny),
 3:  ("元宵",   ("#3A2A7A", "#160F3D"), None, MORTAR, D_lantern),
 4:  ("春天",   ("#5BBF8A", "#2E7D5B"), None, MORTAR, D_spring),
 5:  ("母親節", ("#F28AB0", "#B83C74"), None, MORTAR, D_mom),
 6:  ("端午",   ("#1F9E94", "#0E5A63"), None, MORTAR, D_duanwu),
 7:  ("夏日",   ("#38B6FF", "#0A6FB8"), None, STRAW, D_summer),
 8:  ("父親節", ("#2B4A9C", "#0F1F4D"), None, MORTAR, D_dad),
 9:  ("中秋",   ("#1D2B64", "#0A0F2E"), None, MORTAR, D_moon),
 10: ("萬聖節", ("#5B2A86", "#1E0B33"), None, WITCH, D_hallo),
 11: ("秋楓",   ("#C8691C", "#7A3410"), None, MORTAR, D_autumn),
 12: ("聖誕",   ("#1F7A4D", "#0B3D26"), None, SANTA, D_xmas),
}
for m, (nm, (g1, g2), suit, hat, deco) in M.items():
    s = B.replace('<stop offset="0" stop-color="#3D6CF0"/><stop offset="1" stop-color="#1A3596"/>', f'<stop offset="0" stop-color="{g1}"/><stop offset="1" stop-color="{g2}"/>')
    ring = '<circle cx="256" cy="256" r="200" fill="none" stroke="#fff" stroke-opacity=".08" stroke-width="40"/>'
    assert s.count(ring) == 1
    s = s.replace(ring, ring + f"\n    <!-- {m} 月 {nm} 裝飾 -->\n    <g>{deco()}</g>")
    if suit:
        s = s.replace('fill="#14213D"', f'fill="{suit[0]}"', 1).replace('fill="#1E2E52"', f'fill="{suit[1]}"')
        # 唐裝:白襯衫改金色盤扣
        s = s.replace('<path d="M206 386 L256 470 L306 386 C290 382 272 380 256 380 C240 380 222 382 206 386 Z" fill="#FFFFFF"/>',
                      '<path d="M206 386 L256 470 L306 386 C290 382 272 380 256 380 C240 380 222 382 206 386 Z" fill="#D7263D"/><g stroke="url(#gd)" stroke-width="5" stroke-linecap="round"><path d="M240 420 L272 420 M236 444 L276 444 M240 468 L272 468"/></g>')
        s = s.replace('<path d="M244 400 L268 400 L262 418 L276 476 L256 500 L236 476 L250 418 Z" fill="url(#gd)"/>', '')
    if m == 11:   # 秋天加圍巾
        s = s.replace("    <!-- 耳朵 -->", '    <!-- 圍巾 -->\n    <path d="M184 352 C220 380 292 380 328 352 L336 380 C296 410 216 410 176 380 Z" fill="#C0392B"/><path d="M300 380 L318 452 L292 456 L282 392 Z" fill="#A93226"/><path d="M190 368 C226 392 286 392 322 368" stroke="#F5CBA7" stroke-width="4" stroke-dasharray="8 8" fill="none"/>\n    <!-- 耳朵 -->')
    a, _, c = cut(s, "    <!-- 博士帽 -->", "    <!-- 眼睛")
    s = a + hat + c
    a, _, c = cut(s, "    <!-- 精打細算", "  </g>\n</svg>")
    s = a + P[m] + c
    open(os.path.join(out, f"logo-m{m:02d}.svg"), "w", encoding="utf-8").write(s)
print("ok", len(M))
