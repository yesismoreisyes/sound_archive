"""
KD Archive Deck (Portable) — Blender 4.0 build & layer render script
=====================================================================
Blender > Scripting 탭 > Text > Open 으로 이 파일을 열고 ▶ Run Script.

1) MODE = "preview" : 장면을 만들고 원근 미리보기 한 장만 렌더 (2~4분)
2) MODE = "plate"   : 본체 · 롤러 위 플랜지 · layout.json만 다시 렌더 (5분 안팎)
3) MODE = "all"     : 웹사이트용 레이어 전부 렌더 (20~30분)
   - 릴 회전 프레임, 노브 프레임, 버튼, 미터 유리, 본체, 카메라 투영 정보(layout.json)
   렌더하는 동안 Blender 화면이 멈춘 것처럼 보이는 건 정상입니다.

결과물: 바탕화면/tape_deck_render/ 폴더
"""
import bpy, bmesh, os, math, json
from mathutils import Matrix, Vector
from bpy_extras.object_utils import world_to_camera_view

# ------------------------------------------------------------------
# 설정
# ------------------------------------------------------------------
MODE        = "preview"   # "preview", "plate"(본체·롤러·layout만, 5분), "all"(전부, 20~30분)
SCALE       = 2           # 2 = 레티나용 3200x2000 기준
SAMPLES     = 64          # 노이즈가 보이면 128
REEL_FRAMES = 30          # 릴 120° 회전을 몇 장으로 나눌지
KNOB_FRAMES = 48
EXPOSURE    = -1.0        # 전체 밝기. 어두우면 -0.6, 밝으면 -1.4
CAM_LENS    = 50          # 렌즈(mm). 작을수록 원근이 강해짐 (35~85)
CAM_HEIGHT  = 0.40        # 카메라 높이(m). 높을수록 위에서 내려다봄
SHADOW      = True        # 기계 아래 바닥 그림자 (투명 배경 위에 반투명으로 남음). 끄려면 False
OUT = os.path.join(os.path.expanduser("~"), "Desktop", "tape_deck_render")

# 실제 휴대용 녹음기 크기 (m)
BW, BD, BH = 0.34, 0.25, 0.11                 # 본체 폭, 깊이, 높이
FRONT_Y = -BD / 2

# 윗면 (TOP 로컬 좌표: x, y = 윗면 위 위치, z = 윗면에서 높이)
REEL_C   = [(-0.085, 0.045), (0.085, 0.045)]
REEL_R, PACK_R, HUB_R = 0.065, 0.058, 0.012
PACK_Z   = (0.0051, 0.0113)                   # 감긴 테이프 아래·위 높이 (1/4인치 폭)
ROLLERS  = [(-0.135, -0.06), (0.135, -0.06)]
ROLLER_R = 0.011
TAPE_Z   = (0.0051, 0.0113)                   # 테이프 띠 아래·위 높이 (롤러 홈 안)
TAPE_Y   = ROLLERS[0][1] - ROLLER_R

# 앞면 (FRONT 로컬 좌표: x, y = 바닥에서 높이, z = 앞면에서 튀어나온 거리)
METERS   = [(-0.072, 0.052), (-0.016, 0.052)]
METER_WIN, METER_BEZEL, PIVOT_DY, NEEDLE_L = 0.021, 0.025, -0.011, 0.0245
VU_SPAN, VU_MIN, VU_MAX = 45.0, -20.0, 3.0
KNOBS    = {"volume": (-0.125, 0.050), "speed": (0.132, 0.050)}
KNOB_R   = 0.011
KEYS     = [("A", 0.036, "PLAY"), ("B", 0.056, "STOP"), ("C", 0.076, "NEXT"), ("D", 0.096, "PREV")]
KEY_V, KEY_W, KEY_H = 0.042, 0.0165, 0.013
DISPLAY  = (0.066, 0.072, 0.075, 0.019)       # cx, cy, w, h

os.makedirs(OUT, exist_ok=True)
scene = bpy.context.scene

# ------------------------------------------------------------------
# 초기화
# ------------------------------------------------------------------
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
for coll in (bpy.data.meshes, bpy.data.curves, bpy.data.lights, bpy.data.cameras, bpy.data.materials):
    for d in list(coll):
        if d.users == 0:
            coll.remove(d)

G = {}
ALWAYS_HIDDEN = set()
def reg(obj, *groups):
    for g in groups:
        G.setdefault(g, []).append(obj)
    return obj

def link(obj):
    scene.collection.objects.link(obj)
    return obj

# ------------------------------------------------------------------
# 재질
# ------------------------------------------------------------------
def setin(node, names, val):
    for n in names:
        if n in node.inputs:
            node.inputs[n].default_value = val
            return

def mat(name, rgb, metal=0.0, rough=0.5, emit=0.0, trans=0.0, ior=1.45, coat=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    setin(p, ["Base Color"], (*rgb, 1))
    setin(p, ["Metallic"], metal)
    setin(p, ["Roughness"], rough)
    setin(p, ["IOR"], ior)
    if trans:
        setin(p, ["Transmission Weight", "Transmission"], trans)
    if coat:
        setin(p, ["Coat Weight", "Clearcoat"], coat)
    if emit:
        setin(p, ["Emission Color", "Emission"], (*rgb, 1))
        setin(p, ["Emission Strength"], emit)
    return m

def brushed(m, sx=2, sy=300, strength=0.06, rings=False, nscale=4.0):
    nt = m.node_tree; p = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    bump.inputs["Distance"].default_value = 0.0004
    if rings:
        tex = nt.nodes.new("ShaderNodeTexWave")
        tex.wave_type = "RINGS"; tex.rings_direction = "Z"
        tex.inputs["Scale"].default_value = 600
        tex.inputs["Distortion"].default_value = 3.0
        nt.links.new(tc.outputs["Object"], tex.inputs["Vector"])
    else:
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = (sx, sy, 1)
        tex = nt.nodes.new("ShaderNodeTexNoise")
        tex.inputs["Scale"].default_value = nscale
        tex.inputs["Detail"].default_value = 6.0
        nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], tex.inputs["Vector"])
    nt.links.new(tex.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], p.inputs["Normal"])
    return m

def tape_rings(m):
    nt = m.node_tree; p = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    w = nt.nodes.new("ShaderNodeTexWave")
    w.wave_type = "RINGS"; w.rings_direction = "Z"
    w.inputs["Scale"].default_value = 260
    w.inputs["Distortion"].default_value = 1.5
    cr = nt.nodes.new("ShaderNodeValToRGB")
    cr.color_ramp.elements[0].color = (0.010, 0.009, 0.008, 1)
    cr.color_ramp.elements[1].color = (0.030, 0.025, 0.020, 1)
    nt.links.new(tc.outputs["Object"], w.inputs["Vector"])
    nt.links.new(w.outputs["Fac"], cr.inputs["Fac"])
    nt.links.new(cr.outputs["Color"], p.inputs["Base Color"])
    return m

M = {
    "body":     brushed(mat("Body Grey", (0.075, 0.075, 0.073), metal=0.35, rough=0.45), sx=1, sy=1, strength=0.10, nscale=900),
    "deck":     brushed(mat("Deck Silver", (0.62, 0.61, 0.58), metal=0.75, rough=0.30), sx=2, sy=300, strength=0.03),
    "front":    brushed(mat("Front Silver", (0.70, 0.69, 0.66), metal=0.75, rough=0.28), sx=300, sy=2, strength=0.03),
    "headplate":brushed(mat("Head Plate", (0.42, 0.41, 0.39), metal=0.6, rough=0.3)),
    "rubber":   mat("Rubber", (0.012, 0.012, 0.012), rough=0.7),
    "acrylic":  mat("Clear Acrylic", (0.92, 0.94, 0.96), rough=0.05, trans=1.0, ior=1.49),
    "hubplastic": mat("Hub Plastic", (0.55, 0.55, 0.53), rough=0.35),
    "hub":      mat("Hub Dark", (0.10, 0.10, 0.10), metal=0.8, rough=0.3),
    "chrome":   mat("Chrome", (0.80, 0.80, 0.80), metal=1, rough=0.08),
    "satin":    brushed(mat("Satin Alu", (0.72, 0.70, 0.66), metal=0.85, rough=0.25), rings=True, strength=0.04),
    "tape":     tape_rings(mat("Tape Pack", (0.02, 0.018, 0.015), rough=0.28)),
    "face":     mat("Meter Face", (0.93, 0.90, 0.82), rough=0.6, emit=0.25),
    "ink":      mat("Print Ink", (0.03, 0.03, 0.03), rough=0.7),
    "red":      mat("Print Red", (0.55, 0.08, 0.04), rough=0.6),
    "needle":   mat("Needle", (0.02, 0.02, 0.02), rough=0.5),
    "glass":    mat("Glass", (1, 1, 1), rough=0.02, trans=1.0, ior=1.5),
    "screen":   mat("Display", (0.006, 0.005, 0.004), rough=0.25),
    "knob":     mat("Black Knob", (0.012, 0.012, 0.012), rough=0.38),
    "white":    mat("White Paint", (0.88, 0.87, 0.83), rough=0.5),
    "key":      mat("Key Plastic", (0.035, 0.034, 0.032), rough=0.4),
    "well":     mat("Key Well", (0.01, 0.01, 0.01), rough=0.6),
}

# ------------------------------------------------------------------
# 형태 도우미
# ------------------------------------------------------------------
def smooth(obj):
    # 옆면만 매끈하게, 윗면·아랫면은 평평하게 (얇은 원판의 음영 왜곡 방지)
    for f in obj.data.polygons:
        f.use_smooth = abs(f.normal.z) < 0.5
    if hasattr(obj.data, "use_auto_smooth"):
        obj.data.use_auto_smooth = True
        obj.data.auto_smooth_angle = math.radians(40)

def from_bm(name, bm, m, loc=(0, 0, 0)):
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me); ob.location = loc
    me.materials.append(m)
    return link(ob)

def box(name, x, y, z, dx, dy, dz, m, bevel=0.0, rotz=0.0):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Diagonal((dx, dy, dz, 1)))
    ob = from_bm(name, bm, m, (x, y, z)); ob.rotation_euler.z = rotz
    if bevel:
        b = ob.modifiers.new("Bevel", "BEVEL"); b.width = bevel; b.segments = 4; b.limit_method = "ANGLE"
    return ob

def boxes(name, items, m):
    """items: (x, y, z, dx, dy, dz, rotz) — 많은 작은 상자를 한 메시로."""
    bm = bmesh.new()
    for (x, y, z, dx, dy, dz, rz) in items:
        mt = Matrix.Translation((x, y, z)) @ Matrix.Rotation(rz, 4, "Z") @ Matrix.Diagonal((dx, dy, dz, 1))
        bmesh.ops.create_cube(bm, size=1.0, matrix=mt)
    return from_bm(name, bm, m)

def cyl(name, x, y, z, r, depth, m, seg=128):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r, depth=depth)
    ob = from_bm(name, bm, m, (x, y, z)); smooth(ob)
    return ob

def prism(name, pts, z0, z1, m, loc=(0, 0, 0)):
    bm = bmesh.new()
    bot = [bm.verts.new((x, y, z0)) for x, y in pts]
    top = [bm.verts.new((x, y, z1)) for x, y in pts]
    bm.faces.new(list(reversed(bot))); bm.faces.new(top)
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((bot[i], bot[j], top[j], top[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    return from_bm(name, bm, m, loc)

def sector_pts(cx, cy, r1, r2, a0, a1, seg=32):
    out = []
    for i in range(seg + 1):
        a = a0 + (a1 - a0) * i / seg; out.append((cx + r2 * math.cos(a), cy + r2 * math.sin(a)))
    for i in range(seg + 1):
        a = a1 + (a0 - a1) * i / seg; out.append((cx + r1 * math.cos(a), cy + r1 * math.sin(a)))
    return out

def cut(target, cutter):
    b = target.modifiers.new("Cut", "BOOLEAN"); b.operation = "DIFFERENCE"; b.object = cutter; b.solver = "EXACT"
    cutter.hide_render = True; cutter.hide_viewport = True
    ALWAYS_HIDDEN.add(cutter)

FONT = None
for f in ["/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf",
          "/System/Library/Fonts/Supplemental/Futura.ttc"]:
    if os.path.exists(f):
        try:
            FONT = bpy.data.fonts.load(f); break
        except Exception:
            pass

def text(name, body, x, y, size, m, z=0.0006, align="CENTER", extrude=0.0):
    cu = bpy.data.curves.new(name, type="FONT")
    cu.body = body; cu.size = size; cu.align_x = align; cu.align_y = "CENTER"; cu.extrude = extrude
    if FONT: cu.font = FONT
    ob = bpy.data.objects.new(name, cu); ob.location = (x, y, z)
    cu.materials.append(m)
    return link(ob)

def empty(name, x, y, z=0.0):
    e = bpy.data.objects.new(name, None); e.location = (x, y, z)
    return link(e)

def child(obj, parent):
    obj.parent = parent
    return obj

# ------------------------------------------------------------------
# 좌표계: TOP(윗면) · FRONT(앞면) 프레임
# ------------------------------------------------------------------
TOP = empty("Top Frame", 0, 0, BH)
FRONT = empty("Front Frame", 0, FRONT_Y, 0)
FRONT.rotation_euler = (math.radians(90), 0, 0)   # 로컬 x=가로, y=높이, z=바깥쪽

def top_world(x, y, w=0.0):   return (x, y, BH + w)
def front_world(x, v, w=0.0): return (x, FRONT_Y - w, v)

def on(frame, obj):
    obj.parent = frame
    return obj

def cut_on(frame, target, cutter):
    on(frame, cutter); cut(target, cutter)

# ------------------------------------------------------------------
# 본체
# ------------------------------------------------------------------
body = box("Body", 0, 0, BH / 2, BW, BD, BH, M["body"], bevel=0.014)
body.modifiers["Bevel"].segments = 8
reg(body, "plate")
reg(on(TOP, box("Deck Plate", 0, 0, 0.0008, 0.316, 0.222, 0.0016, M["deck"], bevel=0.006)), "plate")
reg(on(FRONT, box("Front Panel", 0, 0.053, 0.0008, 0.316, 0.092, 0.0016, M["front"], bevel=0.004)), "plate")

# 옆면 끈 고리
for sx in (-1, 1):
    for name, off, r, d, m in (("Lug Base", 0.004, 0.010, 0.008, M["satin"]), ("Lug Knurl", 0.010, 0.011, 0.005, M["knob"])):
        o = cyl(f"{name} {sx}", sx * (BW / 2 + off), -0.06, 0.082, r, d, m)
        o.rotation_euler = (0, math.radians(90), 0)
        reg(o, "plate")

def screw(name, frame, x, y, w=0.0016, rot=25, r=0.0025):
    reg(on(frame, cyl(f"Screw {name}", x, y, w, r, 0.0012, M["chrome"], seg=32)), "plate")
    reg(on(frame, box(f"Screw Slot {name}", x, y, w + 0.0006, r * 1.6, r * 0.25, 0.0002, M["hub"], rotz=math.radians(rot))), "plate")

# ------------------------------------------------------------------
# 윗면: 턴테이블, 헤드 블록, 롤러
# ------------------------------------------------------------------
for i, (cx, cy) in enumerate(REEL_C):
    reg(on(TOP, cyl(f"Turntable {i}", cx, cy, 0.002, 0.02, 0.004, M["hub"])), "plate")
    reg(on(TOP, cyl(f"Lower Flange {i}", cx, cy, 0.0045, REEL_R, 0.001, M["acrylic"], seg=192)), "plate")

reg(on(TOP, box("Head Plate", 0, -0.066, 0.0012, 0.17, 0.05, 0.0024, M["headplate"], bevel=0.003)), "plate")
for k, hx in enumerate((-0.04, -0.008, 0.024)):
    reg(on(TOP, box(f"Head Base {k}", hx, -0.054, 0.004, 0.024, 0.022, 0.006, M["headplate"], bevel=0.0015)), "plate")
    reg(on(TOP, box(f"Head {k}", hx, -0.058, 0.012, 0.020, 0.012, 0.016, M["chrome"], bevel=0.002)), "plate")
    reg(on(TOP, box(f"Head Gap {k}", hx, -0.0641, 0.012, 0.0008, 0.0004, 0.010, M["hub"])), "plate")
for gx in (-0.07, 0.042):
    reg(on(TOP, cyl(f"Guide {gx}", gx, TAPE_Y + 0.0035, 0.008, 0.0025, 0.014, M["chrome"], seg=32)), "plate")
reg(on(TOP, cyl("Capstan", 0.058, TAPE_Y + 0.0035, 0.009, 0.0028, 0.016, M["chrome"], seg=32)), "plate")
reg(on(TOP, cyl("Pinch Roller", 0.058, TAPE_Y - 0.0085, 0.008, 0.008, 0.012, M["rubber"])), "plate")
reg(on(TOP, cyl("Pinch Cap", 0.058, TAPE_Y - 0.0085, 0.0142, 0.003, 0.0006, M["chrome"], seg=32)), "plate")
for i, (rx, ry) in enumerate(ROLLERS):
    # 가이드 롤러: 아래 플랜지 · 테이프가 감기는 홈 · 위 플랜지 · 캡
    s = "LR"[i]
    reg(on(TOP, cyl(f"Roller Base {i}", rx, ry, 0.0015, ROLLER_R + 0.004, 0.003, M["rubber"])), "plate")
    reg(on(TOP, cyl(f"Roller Lower Flange {i}", rx, ry, 0.0038, ROLLER_R + 0.0045, 0.0016, M["satin"])), "plate")
    reg(on(TOP, cyl(f"Roller Hub {i}", rx, ry, 0.0082, ROLLER_R, 0.0072, M["chrome"])), "plate")
    reg(on(TOP, cyl(f"Roller Upper Flange {i}", rx, ry, 0.0126, ROLLER_R + 0.0045, 0.0016, M["satin"])), "plate", f"roller_top_{s}")
    reg(on(TOP, cyl(f"Roller Cap {i}", rx, ry, 0.0146, ROLLER_R * 0.75, 0.0024, M["satin"])), "plate", f"roller_top_{s}")
    reg(on(TOP, cyl(f"Roller Screw {i}", rx, ry, 0.0160, 0.0018, 0.0004, M["hub"], seg=24)), "plate", f"roller_top_{s}")
for k, (x, y) in enumerate([(-0.15, 0.104), (0.15, 0.104), (-0.15, -0.104), (0.15, -0.104),
                            (0, 0.1), (0, -0.032), (-0.075, -0.052), (0.075, -0.052)]):
    screw(f"T{k}", TOP, x, y, rot=(k * 53) % 180)
reg(on(TOP, text("Deck Label", "AUDIBILIZATION OF THE UNMOORED", 0, -0.1, 0.0045, M["ink"], z=0.0017)), "plate")

# ------------------------------------------------------------------
# 앞면: 둥근 미터, 노브, 카운터 창, 버튼
# ------------------------------------------------------------------
def amp(db): return 10 ** (db / 20)
def vu_angle(db):
    db = max(VU_MIN, min(VU_MAX, db))
    return -VU_SPAN + 2 * VU_SPAN * (amp(db) - amp(VU_MIN)) / (amp(VU_MAX) - amp(VU_MIN))
def arc_pt(px0, py0, r, deg):
    a = math.radians(deg); return px0 + r * math.sin(a), py0 + r * math.cos(a)

for side, (cx, cy) in zip("LR", METERS):
    pvx, pvy = cx, cy + PIVOT_DY
    reg(on(FRONT, cyl(f"Meter Face {side}", cx, cy, 0.0018, METER_WIN + 0.0005, 0.001, M["face"])), "plate")
    zs = 0.0024
    ink, red = [], []
    for db in [-20, -10, -7, -5, -3, -2, -1, 0, 1, 2, 3]:
        g = vu_angle(db); x, y = arc_pt(pvx, pvy, 0.0196, g)
        (red if db >= 0 else ink).append((x, y, zs, 0.00025, 0.0016, 0.00006, -math.radians(g)))
        if db in (-20, -10, -5, -3, 0, 3):
            tx, ty = arc_pt(pvx, pvy, 0.0226, g)
            reg(on(FRONT, text(f"Meter {side} {db}", (f"+{db}" if db > 0 else str(abs(db))), tx, ty, 0.0021,
                               M["red"] if db >= 0 else M["ink"], z=zs)), "plate")
    g0, g1, g2 = vu_angle(-20), vu_angle(0), vu_angle(3)
    for i in range(40):
        g = g0 + (g1 - g0) * (i + 0.5) / 40; x, y = arc_pt(pvx, pvy, 0.0186, g)
        ink.append((x, y, zs, (g1 - g0) / 40 * math.pi / 180 * 0.0186 * 1.15, 0.0002, 0.00006, -math.radians(g)))
    for i in range(16):
        g = g1 + (g2 - g1) * (i + 0.5) / 16; x, y = arc_pt(pvx, pvy, 0.0184, g)
        red.append((x, y, zs, (g2 - g1) / 16 * math.pi / 180 * 0.0184 * 1.15, 0.0008, 0.00006, -math.radians(g)))
    reg(on(FRONT, boxes(f"Meter Ink {side}", ink, M["ink"])), "plate")
    reg(on(FRONT, boxes(f"Meter Red {side}", red, M["red"])), "plate")
    reg(on(FRONT, text(f"Meter dB {side}", "dB", cx, pvy + 0.0125, 0.0028, M["ink"], z=zs)), "plate")
    reg(on(FRONT, text(f"Meter Ch {side}", side, cx, cy - 0.0168, 0.0028, M["ink"], z=zs)), "plate")

    w0, w1 = 0.00028, 0.00008
    reg(on(FRONT, prism(f"Needle {side}", [(-w0, 0), (w0, 0), (w1, NEEDLE_L), (-w1, NEEDLE_L)], 0, 0.0002, M["needle"],
                        loc=(pvx, pvy, 0.003))), f"needle_{side}")

    bz = on(FRONT, cyl(f"Meter Bezel {side}", cx, cy, 0.002, METER_BEZEL, 0.004, M["satin"]))
    cut_on(FRONT, bz, cyl(f"Meter Window Cutter {side}", cx, cy, 0.002, METER_WIN, 0.02, M["satin"]))
    reg(bz, f"vutop_{side}")
    reg(on(FRONT, cyl(f"Meter Glass {side}", cx, cy, 0.0038, METER_WIN + 0.0005, 0.0004, M["glass"])), f"vutop_{side}")
    reg(on(FRONT, cyl(f"Meter Pivot Cap {side}", pvx, pvy, 0.0036, 0.0032, 0.0016, M["hub"], seg=32)), f"vutop_{side}")

KNOB_EMPTY = {}
def knob_scale(name, cx, cy, marks, ticks):
    items = []
    for p in ticks:
        a = math.radians(-135 + 270 * p)
        items.append((cx + 0.016 * math.sin(a), cy + 0.016 * math.cos(a), 0.0018, 0.0003, 0.0018, 0.00008, -a))
    reg(on(FRONT, boxes(f"{name} Ticks", items, M["ink"])), "plate")
    for p, t in marks:
        a = math.radians(-135 + 270 * p)
        reg(on(FRONT, text(f"{name} {t}", t, cx + 0.0198 * math.sin(a), cy + 0.0198 * math.cos(a), 0.0026, M["ink"], z=0.0018)), "plate")

for key, (cx, cy) in KNOBS.items():
    e = on(FRONT, empty(f"Knob {key}", cx, cy)); KNOB_EMPTY[key] = e
    g = f"knob_{key}"
    reg(on(e, cyl(f"Knob Skirt {key}", 0, 0, 0.0018, KNOB_R + 0.0025, 0.002, M["satin"])), g)
    reg(on(e, cyl(f"Knob Body {key}", 0, 0, 0.0072, KNOB_R, 0.009, M["knob"])), g)
    ridges = [(KNOB_R * math.cos(2 * math.pi * k / 40), KNOB_R * math.sin(2 * math.pi * k / 40), 0.0072,
               0.0007, 0.0009, 0.0086, 2 * math.pi * k / 40) for k in range(40)]
    reg(on(e, boxes(f"Knob Knurl {key}", ridges, M["knob"])), g)
    reg(on(e, cyl(f"Knob Top {key}", 0, 0, 0.0118, KNOB_R - 0.0012, 0.0004, M["satin"])), g)
    reg(on(e, box(f"Knob Pointer {key}", 0, KNOB_R * 0.45, 0.0121, 0.0008, KNOB_R * 0.8, 0.0002, M["ink"])), g)
    reg(on(e, box(f"Knob Skirt Line {key}", 0, KNOB_R + 0.0016, 0.0029, 0.0006, 0.0018, 0.0001, M["ink"])), g)

knob_scale("Vol Scale", *KNOBS["volume"], [(i / 10, str(i)) for i in range(0, 11, 2)], [i / 10 for i in range(11)])
knob_scale("Spd Scale", *KNOBS["speed"], [(0, "3.75"), (0.5, "7.5"), (1, "15")], [0, 0.25, 0.5, 0.75, 1])
reg(on(FRONT, text("Label Volume", "VOLUME", KNOBS["volume"][0], 0.0242, 0.0048, M["ink"], z=0.0018)), "plate")
reg(on(FRONT, text("Label Speed", "TAPE SPEED  IPS", KNOBS["speed"][0], 0.0242, 0.0048, M["ink"], z=0.0018)), "plate")

dcx, dcy, dw, dh = DISPLAY
reg(on(FRONT, box("Display Frame", dcx, dcy, 0.001, dw + 0.003, dh + 0.003, 0.002, M["hub"], bevel=0.001)), "plate")
reg(on(FRONT, box("Display Screen", dcx, dcy, 0.0021, dw, dh, 0.0002, M["screen"])), "plate")

KEY_EMPTY = {}
for letter, x, caption in KEYS:
    reg(on(FRONT, box(f"Key Well {letter}", x, KEY_V, 0.0012, KEY_W + 0.003, KEY_H + 0.003, 0.0008, M["well"], bevel=0.001)), "plate")
    reg(on(FRONT, text(f"Caption {letter}", caption, x, KEY_V - 0.0105, 0.0025, M["ink"], z=0.0018)), "plate")
    e = on(FRONT, empty(f"Key {letter}", x, KEY_V)); KEY_EMPTY[letter] = e
    reg(on(e, box(f"Key Cap {letter}", 0, 0, 0.004, KEY_W, KEY_H, 0.006, M["key"], bevel=0.0015)), f"key_{letter}")
    reg(on(e, text(f"Key Letter {letter}", letter, 0, -0.0006, 0.0065, M["white"], z=0.0071, extrude=0.0001)), f"key_{letter}")

reg(on(FRONT, text("Brand", "KD ARCHIVE DECK", -0.15, 0.091, 0.0045, M["ink"], align="LEFT", z=0.0018)), "plate")
reg(on(FRONT, text("Format", "2-TRACK  ·  1/4 INCH", 0.15, 0.091, 0.0036, M["ink"], align="RIGHT", z=0.0018)), "plate")
for k, sx in enumerate((-1, 1)):
    screw(f"F{k}", FRONT, sx * 0.151, 0.012, rot=30 + 70 * k)

# ------------------------------------------------------------------
# 투명 릴 (회전용 empty 아래) + 감긴 테이프
# ------------------------------------------------------------------
REEL_EMPTY = {}
for side, (cx, cy) in zip("LR", REEL_C):
    reg(on(TOP, cyl(f"Tape Pack {side}", cx, cy, sum(PACK_Z) / 2, PACK_R, PACK_Z[1] - PACK_Z[0], M["tape"])), f"pack_{side}")
    e = on(TOP, empty(f"Reel {side}", cx, cy)); REEL_EMPTY[side] = e
    fl = on(e, cyl(f"Reel Flange {side}", 0, 0, 0.0125, REEL_R, 0.0012, M["acrylic"], seg=192))
    for k in range(3):
        a0 = math.radians(90 + k * 120 - 42); a1 = math.radians(90 + k * 120 + 42)
        cut_on(e, fl, prism(f"Reel Window {side}{k}", sector_pts(0, 0, 0.018, 0.055, a0, a1), 0.0, 0.03, M["acrylic"]))
    reg(fl, f"reel_{side}")
    rim = on(e, cyl(f"Reel Rim {side}", 0, 0, 0.0132, REEL_R, 0.0012, M["acrylic"], seg=192))
    cut_on(e, rim, cyl(f"Reel Rim Cutter {side}", 0, 0, 0.0132, REEL_R - 0.0025, 0.01, M["acrylic"]))
    reg(rim, f"reel_{side}")
    reg(on(e, cyl(f"Reel Hub {side}", 0, 0, 0.0105, HUB_R, 0.007, M["hubplastic"])), f"reel_{side}")
    slots = [(0.0072 * math.cos(math.radians(90 + k * 120)), 0.0072 * math.sin(math.radians(90 + k * 120)), 0.0141,
              0.004, 0.0018, 0.0003, math.radians(90 + k * 120)) for k in range(3)]
    reg(on(e, boxes(f"Hub Slots {side}", slots, M["hub"])), f"reel_{side}")
    reg(on(e, cyl(f"Spindle {side}", 0, 0, 0.0145, 0.0032, 0.003, M["chrome"], seg=32)), f"reel_{side}")

# 미리보기 전용 테이프 띠 (웹에서는 코드가 같은 경로를 실시간으로 그림)
def tape_path(r_left, r_right):
    def tangent_outer(c, r, p, outer_sign):
        dx, dy = p[0] - c[0], p[1] - c[1]; d = math.hypot(dx, dy)
        a = math.atan2(dy, dx); b = math.acos(min(1, r / d))
        c1 = (c[0] + r * math.cos(a + b), c[1] + r * math.sin(a + b))
        c2 = (c[0] + r * math.cos(a - b), c[1] + r * math.sin(a - b))
        return c1 if (c1[0] - c2[0]) * outer_sign > 0 else c2
    (lx, ly), (rx, ry) = ROLLERS
    pl, pr = (lx - ROLLER_R, ly), (rx + ROLLER_R, ry)
    pts = [tangent_outer(REEL_C[0], r_left, pl, -1), pl]
    pts += [(lx + ROLLER_R * math.cos(math.pi + math.pi / 2 * k / 8), ly + ROLLER_R * math.sin(math.pi + math.pi / 2 * k / 8)) for k in range(1, 9)]
    pts += [(rx + ROLLER_R * math.cos(1.5 * math.pi + math.pi / 2 * k / 8), ry + ROLLER_R * math.sin(1.5 * math.pi + math.pi / 2 * k / 8)) for k in range(0, 9)]
    pts.append(tangent_outer(REEL_C[1], r_right, pr, 1))
    return pts

items = []
pts = tape_path(PACK_R, PACK_R * 0.55)
for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
    L = math.hypot(x1 - x0, y1 - y0)
    if L > 1e-7:
        items.append(((x0 + x1) / 2, (y0 + y1) / 2, sum(TAPE_Z) / 2, L + 0.0002, 0.00025, TAPE_Z[1] - TAPE_Z[0], math.atan2(y1 - y0, x1 - x0)))
reg(on(TOP, boxes("Tape Preview", items, M["tape"])), "tape_preview")

# 그림자를 받는 바닥 (투명 배경 위에 그림자만 남음)
catcher = box("Shadow Catcher", 0, 0, -0.0005, 3, 3, 0.001, M["well"])
catcher.is_shadow_catcher = True
reg(catcher, "catcher")

# ------------------------------------------------------------------
# 조명 · 카메라 · 렌더 설정
# ------------------------------------------------------------------
def area(name, loc, size, energy, target=(0, 0, 0.05)):
    ld = bpy.data.lights.new(name, "AREA"); ld.size = size; ld.energy = energy
    ob = link(bpy.data.objects.new(name, ld)); ob.location = loc
    d = Vector(target) - Vector(loc)
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return ob

area("Softbox", (0.0, -0.45, 0.9), 1.0, 38)
area("Key", (-0.7, -0.35, 0.55), 0.5, 26)
area("Rim", (0.55, 0.7, 0.5), 0.6, 22)

world = scene.world or bpy.data.worlds.new("World"); scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
bg.inputs["Color"].default_value = (0.32, 0.32, 0.315, 1); bg.inputs["Strength"].default_value = 1.0

cam_d = bpy.data.cameras.new("Camera"); cam_d.lens = CAM_LENS; cam_d.sensor_width = 36; cam_d.sensor_fit = "HORIZONTAL"
cam_d.clip_start = 0.01; cam_d.clip_end = 10
cam = link(bpy.data.objects.new("Camera", cam_d))
cam.location = (0, -0.62, CAM_HEIGHT)
cam.rotation_euler = (Vector((0, -0.005, 0.05)) - cam.location).to_track_quat("-Z", "Y").to_euler()
scene.camera = cam

r = scene.render
r.engine = "CYCLES"
r.resolution_x, r.resolution_y, r.resolution_percentage = int(1600 * SCALE), int(1000 * SCALE), 100
r.film_transparent = True
r.image_settings.file_format = "PNG"; r.image_settings.color_mode = "RGBA"; r.image_settings.color_depth = "8"
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
try:
    scene.view_settings.view_transform = "AgX"
except Exception:
    scene.view_settings.view_transform = "Filmic"
try:
    scene.view_settings.look = "AgX - Medium High Contrast"
except Exception:
    pass
scene.view_settings.exposure = EXPOSURE
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"; prefs.get_devices()
    for d in prefs.devices: d.use = True
    scene.cycles.device = "GPU"
except Exception as ex:
    print("GPU 설정 실패, CPU로 렌더:", ex)

# ------------------------------------------------------------------
# 렌더 도우미
# ------------------------------------------------------------------
def proj(co):
    v = world_to_camera_view(scene, cam, Vector(co))
    return v.x * 1600, (1 - v.y) * 1000

def group_box(groups, margin=10):
    bpy.context.view_layer.update()
    xs, ys = [], []
    for g in groups:
        for o in G.get(g, []):
            for c in o.bound_box:
                x, y = proj(o.matrix_world @ Vector(c)); xs.append(x); ys.append(y)
    x0 = max(0, math.floor(min(xs)) - margin); y0 = max(0, math.floor(min(ys)) - margin)
    x1 = min(1600, math.ceil(max(xs)) + margin); y1 = min(1000, math.ceil(max(ys)) + margin)
    return [x0, y0, x1, y1]

def set_border(box_px):
    if box_px is None:
        r.use_border = False; r.use_crop_to_border = False; return
    x0, y0, x1, y1 = box_px
    r.use_border = True; r.use_crop_to_border = True
    r.border_min_x, r.border_max_x = x0 / 1600, x1 / 1600
    r.border_min_y, r.border_max_y = 1 - y1 / 1000, 1 - y0 / 1000

def render(fname, groups, box_px=None, samples=SAMPLES, glass_alpha=True):
    show = set()
    for g in groups: show.update(G.get(g, []))
    for o in scene.objects:
        if o.type in ("LIGHT", "CAMERA", "EMPTY") or o in ALWAYS_HIDDEN:
            continue
        o.hide_render = o not in show
    set_border(box_px)
    scene.cycles.samples = samples
    scene.cycles.film_transparent_glass = glass_alpha
    r.filepath = os.path.join(OUT, fname)
    print("렌더:", fname)
    bpy.ops.render.render(write_still=True)

def stitch(paths, out_path):
    import numpy as np
    imgs = [bpy.data.images.load(p) for p in paths]
    w, h = imgs[0].size
    arrs = []
    for im in imgs:
        a = np.empty(w * h * 4, dtype=np.float32); im.pixels.foreach_get(a); arrs.append(a.reshape(h, w, 4))
    strip = np.concatenate(arrs[::-1], axis=0)       # 0번 프레임이 맨 위
    out = bpy.data.images.new(os.path.basename(out_path), w, h * len(arrs), alpha=True)
    out.pixels.foreach_set(strip.ravel())
    out.filepath_raw = out_path; out.file_format = "PNG"; out.save()
    for im in imgs: bpy.data.images.remove(im)

def frames(prefix, groups, box_px, count, set_frame, samples):
    os.makedirs(os.path.join(OUT, "frames"), exist_ok=True)
    paths = []
    for k in range(count):
        set_frame(k)
        f = os.path.join("frames", f"{prefix}_{k:02d}.png"); paths.append(os.path.join(OUT, f))
        render(f, groups, box_px, samples=samples)
    try:
        stitch(paths, os.path.join(OUT, f"{prefix}_strip.png"))
    except Exception as ex:
        print("프레임 합치기 실패 (개별 프레임은 frames/ 폴더):", prefix, ex)

ALL = [g for g in G if g not in ("catcher", "tape_preview") and not g.startswith("roller_top")]

def preview_pose():
    G["pack_R"][0].scale = (0.55, 0.55, 1)
    G["needle_L"][0].rotation_euler.z = -math.radians(vu_angle(-4))
    G["needle_R"][0].rotation_euler.z = -math.radians(vu_angle(-7))
    KNOB_EMPTY["volume"].rotation_euler.z = -math.radians(-135 + 270 * 0.7)
    REEL_EMPTY["L"].rotation_euler.z = math.radians(25)
    REEL_EMPTY["R"].rotation_euler.z = math.radians(70)

def neutral_pose():
    G["pack_R"][0].scale = (1, 1, 1)
    for s in "LR":
        G[f"needle_{s}"][0].rotation_euler.z = 0
        REEL_EMPTY[s].rotation_euler.z = 0
    for e in KNOB_EMPTY.values(): e.rotation_euler.z = 0
    for e in KEY_EMPTY.values(): e.location.z = 0

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "tape_deck.blend"))

preview_pose()
render("preview.png", ALL + ["tape_preview"] + (["catcher"] if SHADOW else []), glass_alpha=False)
neutral_pose()

if MODE in ("all", "plate"):
    FULL = MODE == "all"
    layers = {}
    # 본체: 노브·버튼은 기본 상태로 함께 렌더해 그림자를 남김 (위에 프레임 이미지가 덮음)
    keep = ["plate"] + (["catcher"] if SHADOW else []) + [f"knob_{k}" for k in KNOBS] + [f"key_{l}" for l, _, _ in KEYS]
    render("plate.png", keep, glass_alpha=False)
    layers["plate"] = {"file": "plate.png", "box": [0, 0, 1600, 1000]}

    # 롤러 위 플랜지: 웹에서 테이프 위에 덮어 그림 (테이프가 롤러 홈에 걸린 모습)
    layers["roller_tops"] = []
    for s in "LR":
        b = group_box([f"roller_top_{s}"], margin=6)
        render(f"roller_top_{s}.png", [f"roller_top_{s}"], b)
        layers["roller_tops"].append({"file": f"roller_top_{s}.png", "box": b})

    layers["glass"] = []
    for s in "LR":
        b = group_box([f"vutop_{s}"])
        if FULL: render(f"glass_{s}.png", [f"vutop_{s}"], b)
        layers["glass"].append({"file": f"glass_{s}.png", "box": b})

    layers["reels"] = []
    for s in "LR":
        b = group_box([f"reel_{s}"])
        def setf(k, s=s): REEL_EMPTY[s].rotation_euler.z = -math.radians(120 * k / REEL_FRAMES)
        if FULL: frames(f"reel_{s}", [f"reel_{s}"], b, REEL_FRAMES, setf, max(32, SAMPLES // 2))
        REEL_EMPTY[s].rotation_euler.z = 0
        layers["reels"].append({"file": f"reel_{s}_strip.png", "box": b, "frames": REEL_FRAMES,
                                "deg_per_frame": 120 / REEL_FRAMES, "direction": "clockwise_from_top"})

    layers["knobs"] = {}
    for key in KNOBS:
        b = group_box([f"knob_{key}"])
        def setk(k, key=key): KNOB_EMPTY[key].rotation_euler.z = -math.radians(-135 + 270 * k / (KNOB_FRAMES - 1))
        if FULL: frames(f"knob_{key}", [f"knob_{key}"], b, KNOB_FRAMES, setk, max(24, SAMPLES // 2))
        KNOB_EMPTY[key].rotation_euler.z = 0
        layers["knobs"][key] = {"file": f"knob_{key}_strip.png", "box": b, "frames": KNOB_FRAMES,
                                "angle_min": -135, "angle_max": 135}

    layers["keys"] = []
    for letter, x, _ in KEYS:
        b = group_box([f"key_{letter}"], margin=6)
        KEY_EMPTY[letter].location.z = 0
        if FULL: render(f"key_{letter}_up.png", [f"key_{letter}"], b)
        KEY_EMPTY[letter].location.z = -0.0015
        if FULL: render(f"key_{letter}_down.png", [f"key_{letter}"], b)
        KEY_EMPTY[letter].location.z = 0
        layers["keys"].append({"letter": letter, "up": f"key_{letter}_up.png", "down": f"key_{letter}_down.png", "box": b})

    # 카메라 투영 행렬: 웹에서 3D 좌표 → 화면 좌표 (pack, 테이프, 바늘, 카운터 창)
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    P = cam.calc_matrix_camera(dg, x=r.resolution_x, y=r.resolution_y, scale_x=r.pixel_aspect_x, scale_y=r.pixel_aspect_y)
    MVP = P @ cam.matrix_world.inverted()
    test = Vector((0.1, -0.05, BH)); h = MVP @ test.to_4d()
    print("투영 검증:", ((h.x / h.w + 1) / 2 * 1600, (1 - h.y / h.w) / 2 * 1000), proj(test))

    dx0, dy0 = dcx - dw / 2, dcy + dh / 2
    layout = {
        "canvas": [1600, 1000], "scale": SCALE, "units": "meters, z up, y toward back",
        "mvp": [list(row) for row in MVP],
        "reels": [{"center": list(top_world(x, y)), "pack_z": [BH + PACK_Z[0], BH + PACK_Z[1]]} for x, y in REEL_C],
        "pack_r": [HUB_R + 0.003, PACK_R],
        "rollers": [{"center": list(top_world(x, y)), "r": ROLLER_R} for x, y in ROLLERS],
        "tape": {"z": [BH + TAPE_Z[0], BH + TAPE_Z[1]], "front_y": TAPE_Y},
        "needles": [{"pivot": list(front_world(x, y + PIVOT_DY, 0.0031)), "length": NEEDLE_L,
                     "span_deg": VU_SPAN, "db_min": VU_MIN, "db_max": VU_MAX} for x, y in METERS],
        "display": [list(front_world(dx0, dy0, 0.0022)), list(front_world(dx0 + dw, dy0, 0.0022)),
                    list(front_world(dx0 + dw, dy0 - dh, 0.0022)), list(front_world(dx0, dy0 - dh, 0.0022))],
        "layers": layers,
    }
    with open(os.path.join(OUT, "layout.json"), "w") as fh:
        json.dump(layout, fh, indent=2)

set_border(None)
for o in scene.objects:
    if o not in ALWAYS_HIDDEN and o.type not in ("LIGHT", "CAMERA", "EMPTY"):
        o.hide_render = o in G["catcher"] or o in G["tape_preview"]
bpy.ops.wm.save_mainfile()
print("완료:", OUT)
