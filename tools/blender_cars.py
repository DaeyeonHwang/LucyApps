# 카 몬스터 레이스 자동차 5대를 Blender로 렌더링한다.
# 실행: & "D:\Blender\blender.exe" --background --factory-startup --python tools/blender_cars.py -- <출력폴더> [0 1 2 3 4] [--samples N]
# 결과: <출력폴더>/car0.webp ... car4.webp (750x420, 투명 배경, 바닥 그림자 포함)
# 좌표: 예전 SVG(200x112) 좌표를 그대로 쓴다. X = (x-100)/100, Z = (112-y)/100, 차 앞은 +X, 카메라 쪽 옆면은 -Y
# 실제 차종이나 다른 게임의 자동차를 따라 하지 않는 장난감 자동차 모양이다.
import bpy, sys, math, os, re
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
OUT = os.path.abspath(argv[0] if argv else 'cars')
SAMPLES = 96
ONLY = []
i = 1
while i < len(argv):
    if argv[i] == '--samples':
        SAMPLES = int(argv[i + 1]); i += 2; continue
    ONLY.append(int(argv[i])); i += 1
ONLY = ONLY or [0, 1, 2, 3, 4]
os.makedirs(OUT, exist_ok=True)

# ---------- SVG 경로 → 점 목록 ----------
def path_points(d, step=10):
    toks = re.findall(r'[MLHVQCZmlhvqcz]|-?\d*\.?\d+', d)
    pts, cur, cmd, k = [], (0, 0), None, 0
    def num():
        nonlocal k
        v = float(toks[k]); k += 1; return v
    while k < len(toks):
        t = toks[k]
        if re.match(r'[A-Za-z]', t):
            cmd = t; k += 1
            if cmd in 'Zz':
                continue
        if cmd == 'M' or cmd == 'L':
            cur = (num(), num()); pts.append(cur)
        elif cmd == 'H':
            cur = (num(), cur[1]); pts.append(cur)
        elif cmd == 'V':
            cur = (cur[0], num()); pts.append(cur)
        elif cmd == 'Q':
            c1 = (num(), num()); p = (num(), num())
            for s in range(1, step + 1):
                u = s / step
                pts.append(((1-u)**2*cur[0] + 2*(1-u)*u*c1[0] + u*u*p[0], (1-u)**2*cur[1] + 2*(1-u)*u*c1[1] + u*u*p[1]))
            cur = p
        elif cmd == 'C':
            c1 = (num(), num()); c2 = (num(), num()); p = (num(), num())
            for s in range(1, step + 1):
                u = s / step; a, b, c, e = (1-u)**3, 3*(1-u)**2*u, 3*(1-u)*u*u, u**3
                pts.append((a*cur[0] + b*c1[0] + c*c2[0] + e*p[0], a*cur[1] + b*c1[1] + c*c2[1] + e*p[1]))
            cur = p
        else:
            k += 1
    # 겹치는 점 정리
    out = []
    for p in pts:
        if not out or abs(out[-1][0]-p[0]) + abs(out[-1][1]-p[1]) > 0.05:
            out.append(p)
    if len(out) > 2 and abs(out[0][0]-out[-1][0]) + abs(out[0][1]-out[-1][1]) < 0.05:
        out.pop()
    return out

def clip_above(poly, ylim):
    """SVG y가 ylim보다 작은(=더 높은) 부분만 남긴다."""
    out = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        ina, inb = a[1] <= ylim, b[1] <= ylim
        if ina:
            out.append(a)
        if ina != inb:
            t = (ylim - a[1]) / (b[1] - a[1])
            out.append((a[0] + t*(b[0]-a[0]), ylim))
    return out

def P(x, y):
    return ((x - 100) / 100.0, (112 - y) / 100.0)

# ---------- 재질 ----------
MATS = {}
def mat(name, color, metal=0.0, rough=0.35, coat=0.0, emit=None, estr=0.0, alpha=1.0, grad=None):
    if name in MATS:
        return MATS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bs = nt.nodes['Principled BSDF']
    bs.inputs['Base Color'].default_value = (*color, 1)
    bs.inputs['Metallic'].default_value = metal
    bs.inputs['Roughness'].default_value = rough
    if coat:
        bs.inputs['Coat Weight'].default_value = coat
        bs.inputs['Coat Roughness'].default_value = 0.05
    if emit:
        bs.inputs['Emission Color'].default_value = (*emit, 1)
        bs.inputs['Emission Strength'].default_value = estr
    if grad:  # 위는 밝게, 아래는 진하게 (오브젝트 Z 기준)
        tc = nt.nodes.new('ShaderNodeTexCoord')
        sep = nt.nodes.new('ShaderNodeSeparateXYZ')
        mr = nt.nodes.new('ShaderNodeMapRange')
        mr.inputs['From Min'].default_value = grad[0]
        mr.inputs['From Max'].default_value = grad[1]
        ramp = nt.nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].color = (*grad[2], 1)
        ramp.color_ramp.elements[1].color = (*grad[3], 1)
        nt.links.new(tc.outputs['Object'], sep.inputs[0])
        # 옆모습 판(curve)은 X축으로 90° 돌려 두어서 로컬 Y가 실제 높이다
        nt.links.new(sep.outputs['Y'], mr.inputs['Value'])
        nt.links.new(mr.outputs['Result'], ramp.inputs['Fac'])
        nt.links.new(ramp.outputs['Color'], bs.inputs['Base Color'])
    MATS[name] = m
    return m

def srgb(h):
    h = h.lstrip('#')
    c = [int(h[i:i+2], 16) / 255 for i in (0, 2, 4)]
    return tuple(((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92 for v in c)

def paint(hexc, name):
    return mat(name, srgb(hexc), metal=0.0, rough=0.28, coat=1.0)

GLASS = None
def glass():
    global GLASS
    if not GLASS:
        GLASS = mat('glass', srgb('#16233f'), rough=0.05, coat=1.0, grad=(0.35, 0.85, srgb('#0b1630'), srgb('#7fb4ec')))
    return GLASS

def dark():   return mat('dark', srgb('#1d1f27'), rough=0.6)
def rubber(): return mat('rubber', srgb('#1a1c22'), rough=0.85)
def chrome(): return mat('chrome', srgb('#e6eaf0'), metal=1.0, rough=0.12)
def gold():   return mat('gold', srgb('#f2b92b'), metal=1.0, rough=0.2)
def white():  return mat('white', srgb('#f7f8fb'), rough=0.3, coat=1.0)
def head():   return mat('headlight', (1, 1, 0.9), rough=0.1, emit=(1, 0.97, 0.8), estr=6)
def tail():   return mat('taillight', srgb('#ff2b40'), rough=0.2, emit=srgb('#ff2b40'), estr=3)
def amber():  return mat('amber', srgb('#ffe98a'), rough=0.2, emit=srgb('#ffe98a'), estr=4)

# ---------- 모양 만드는 도우미 ----------
def link(ob):
    bpy.context.scene.collection.objects.link(ob)
    return ob

def slab(name, pts_svg, half, m, bevel=0.03, y=0.0, res=3):
    """SVG 옆모습 점들을 Y 방향으로 두께 2*half만큼 뽑는다 (둥근 모서리)."""
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '2D'
    cu.fill_mode = 'BOTH'
    cu.extrude = max(half - bevel, 0.001)
    cu.bevel_depth = bevel
    cu.bevel_resolution = res
    sp = cu.splines.new('POLY')
    pts = [P(*p) for p in pts_svg]
    sp.points.add(len(pts) - 1)
    for p, (x, z) in zip(sp.points, pts):
        p.co = (x, z, 0, 1)
    sp.use_cyclic_u = True
    ob = link(bpy.data.objects.new(name, cu))
    ob.rotation_euler = (math.radians(90), 0, 0)
    ob.location = (0, y, 0)
    cu.materials.append(m)
    return ob

def tube(name, pts_svg, r, m, y):
    """옆면에 붙는 줄무늬·번개 (둥근 관)."""
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    cu.bevel_depth = r
    cu.bevel_resolution = 2
    cu.use_fill_caps = True
    sp = cu.splines.new('POLY')
    pts = [P(*p) for p in pts_svg]
    sp.points.add(len(pts) - 1)
    for p, (x, z) in zip(sp.points, pts):
        p.co = (x, y, z, 1)
    ob = link(bpy.data.objects.new(name, cu))
    cu.materials.append(m)
    return ob

def box(name, c_svg, size, m, y=0.0, bev=0.01):
    x, z = P(*c_svg)
    me = bpy.data.meshes.new(name)
    sx, sy, sz = size
    v = [(x+a*sx/2, y+b*sy/2, z+c*sz/2) for a in (-1, 1) for b in (-1, 1) for c in (-1, 1)]
    f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    me.from_pydata(v, [], f)
    ob = link(bpy.data.objects.new(name, me))
    ob.data.materials.append(m)
    if bev:
        bm = ob.modifiers.new('bev', 'BEVEL'); bm.width = bev; bm.segments = 3
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob

def sphere(name, c_svg, r, m, y=0.0, scale=(1, 1, 1)):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, segments=32, ring_count=16, location=(*[P(*c_svg)[0]], y, P(*c_svg)[1]))
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = scale
    ob.data.materials.append(m)
    bpy.ops.object.shade_smooth()
    return ob

def cyl(name, c_svg, r, depth, m, y=0.0, axis='Y', verts=48, bev=0.0):
    x, z = P(*c_svg)
    rot = (math.radians(90), 0, 0) if axis == 'Y' else (0, math.radians(90), 0) if axis == 'X' else (0, 0, 0)
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=depth, location=(x, y, z), rotation=rot)
    ob = bpy.context.active_object
    ob.name = name
    ob.data.materials.append(m)
    if bev:
        bm = ob.modifiers.new('bev', 'BEVEL'); bm.width = bev; bm.segments = 4; bm.limit_method = 'ANGLE'
    bpy.ops.object.shade_smooth()
    return ob

def text(name, s, c_svg, size, m, y):
    cu = bpy.data.curves.new(name, 'FONT')
    cu.body = s
    cu.align_x = 'CENTER'; cu.align_y = 'CENTER'
    cu.size = size
    cu.extrude = 0.004
    ob = link(bpy.data.objects.new(name, cu))
    x, z = P(*c_svg)
    ob.location = (x, y, z)
    ob.rotation_euler = (math.radians(90), 0, 0)
    cu.materials.append(m)
    return ob

def wheel(tag, c_svg, r, ycenter, width, rim_m, tread=False, spokes=5):
    x, z = P(*c_svg)
    R = r / 100.0
    side = -1 if ycenter < 0 else 1
    t = cyl(f'{tag}_tire', c_svg, R, width, rubber(), y=ycenter, bev=R*0.28 if not tread else R*0.2)
    if tread:  # 울퉁불퉁한 몬스터트럭 바퀴
        for k in range(18):
            a = k / 18 * 2 * math.pi
            bpy.ops.mesh.primitive_cube_add(size=1, location=(x + math.cos(a)*R*0.97, ycenter, z + math.sin(a)*R*0.97),
                                            rotation=(0, -a, 0))
            lug = bpy.context.active_object
            lug.scale = (R*0.12, width*0.9, R*0.2)
            lug.data.materials.append(rubber())
    face = ycenter + side * width / 2
    cyl(f'{tag}_rim', c_svg, R*0.64, 0.02, rim_m, y=face - side*0.004, bev=0.006)
    cyl(f'{tag}_hubdark', c_svg, R*0.5, 0.022, dark(), y=face - side*0.002)
    for k in range(spokes):
        a = k / spokes * 2 * math.pi + math.pi/2
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x + math.cos(a)*R*0.3, face + side*0.006, z + math.sin(a)*R*0.3),
                                        rotation=(0, -a, 0))
        sp = bpy.context.active_object
        sp.scale = (R*0.42, 0.02, R*0.11)
        sp.data.materials.append(rim_m)
        bm = sp.modifiers.new('bev', 'BEVEL'); bm.width = 0.004; bm.segments = 2
    cyl(f'{tag}_cap', c_svg, R*0.15, 0.04, rim_m, y=face + side*0.01, bev=0.008)

def cut_wells(body, wheels, half):
    """차체에 바퀴 자리를 판다 (curve → mesh 바꾼 뒤 boolean)."""
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(body.evaluated_get(dg))
    ob = link(bpy.data.objects.new(body.name + '_m', me))
    ob.matrix_world = body.matrix_world
    bpy.data.objects.remove(body)
    for k, (c, r) in enumerate(wheels):
        cut = cyl(f'cut{k}', c, r/100.0 + 0.035, half*2 + 0.3, dark())
        cut.hide_render = True; cut.hide_viewport = True
        b = ob.modifiers.new(f'well{k}', 'BOOLEAN'); b.object = cut; b.operation = 'DIFFERENCE'; b.solver = 'EXACT'
    for p in ob.data.polygons:
        p.use_smooth = True
    ws = ob.modifiers.new('wn', 'WEIGHTED_NORMAL'); ws.keep_sharp = True
    # 바퀴집 안쪽은 어둡게
    return ob

def well_liner(c, r, half):
    cyl('liner', c, r/100.0 + 0.03, half*2 - 0.02, mat('liner', srgb('#0b0f1c'), rough=0.9))

def cabin(body_pts, belt, roof_cut, half, body_m, extra=0.0):
    """창문 유리(앞유리·뒷유리 포함)와 지붕."""
    gh = clip_above(body_pts, belt)
    slab('glass', gh, half*0.86, glass(), bevel=0.05 + extra)
    rf = clip_above(body_pts, roof_cut)
    if len(rf) >= 3:
        slab('roof', rf, half*0.8, body_m, bevel=0.065 + extra)

# ---------- 자동차 5대 ----------
def car0():  # 강철 몬스터트럭
    m = mat('p0', srgb('#a9b3c4'), metal=0.9, rough=0.22, coat=1.0)
    d = 'M12 66 L14 46 Q15 42 20 42 L58 40 L76 20 Q78 18 82 18 L130 18 Q134 18 136 20 L152 40 L186 42 Q192 43 192 50 L192 66 Z'
    pts = path_points(d)
    H = 0.42
    b = slab('body', pts, H, m, bevel=0.035)
    cabin(pts, 40, 21, H, m)
    for w, wd in (('M82 24 L104 24 L104 40 L66 40 Z', 0), ('M110 24 L130 24 L144 40 L110 40 Z', 0)):
        slab('win', path_points(w), 0.004, glass(), bevel=0.003, y=-H - 0.004)
    # 몸통 아래 받침과 쇼크업소버
    box('frame', (100, 70), (1.3, 0.5, 0.08), dark())
    for x in (46, 154):
        for yy in (-0.22, 0.22):
            box('shock', (x, 72), (0.05, 0.05, 0.22), mat('orange', srgb('#ff8a1f'), metal=0.6, rough=0.3), y=yy, bev=0.008)
    # 지붕 조명
    box('lightbar', (106, 15), (0.46, 0.34, 0.06), dark(), y=0)
    for k, x in enumerate((92, 101, 110, 119)):
        cyl(f'roofl{k}', (x, 15), 0.022, 0.02, amber(), y=-0.172)
    # 앞 범퍼, 헤드라이트, 꼬리등
    box('bumper', (195, 60), (0.06, 0.8, 0.12), chrome(), bev=0.02)
    box('hl', (189, 47), (0.03, 0.12, 0.05), head(), y=-0.28)
    box('hl2', (189, 47), (0.03, 0.12, 0.05), head(), y=0.28)
    box('tl', (12.5, 51), (0.02, 0.1, 0.07), tail(), y=-0.3)
    tube('stripe', [(18, 46), (60, 44)], 0.008, white(), -H - 0.006)
    tube('stripe2', [(152, 44), (188, 46)], 0.008, white(), -H - 0.006)
    for x in (46, 154):
        for yy in (-1, 1):
            wheel(f'w{x}{yy}', (x, 84), 24, yy*0.5, 0.3, chrome(), tread=True)
    return [(46, 84, 24), (154, 84, 24)]

def car1():  # 파란 번개 (슈퍼카)
    m = paint('#2563eb', 'p1')
    d = 'M8 84 C6 74 10 68 22 66 L58 60 C76 50 92 40 118 40 C138 40 152 48 166 58 L186 62 C194 64 197 72 195 84 Z'
    pts = path_points(d)
    H = 0.38
    b = slab('body', pts, H, m, bevel=0.045)
    b = cut_wells(b, [((48, 88), 17), ((156, 88), 17)], H)
    for c in ((48, 88), (156, 88)):
        well_liner(c, 17, H)
    slab('glass', path_points('M60 60 C76 50 92 40 118 40 C138 40 152 48 164 58 Z'), H*0.84, glass(), bevel=0.055)
    slab('win', path_points('M70 60 C84 50 98 45 118 45 C130 45 140 50 148 58 Z'), 0.004, glass(), bevel=0.003, y=-H - 0.004)
    tube('pillar', [(112, 45.5), (116, 58)], 0.012, m, -H - 0.01)
    # 번개 줄무늬
    tube('bolt', [(38, 74), (68, 70), (60, 76), (98, 71)], 0.024, mat('yellow', srgb('#ffd84a'), rough=0.3, coat=1.0), -H - 0.008)
    slab('intake', path_points('M120 66 L152 63 L142 76 L124 76 Z'), 0.004, dark(), bevel=0.003, y=-H - 0.004)
    # 뒷날개
    box('wing', (16, 59), (0.16, 0.6, 0.022), mat('p1d', srgb('#0f2a78'), rough=0.3, coat=1.0), bev=0.008)
    for yy in (-0.22, 0.22):
        box('wpost', (18, 64), (0.03, 0.03, 0.08), dark(), y=yy, bev=0.004)
    box('hl', (186, 66), (0.04, 0.16, 0.035), head(), y=-0.24)
    box('hl2', (186, 66), (0.04, 0.16, 0.035), head(), y=0.24)
    box('tl', (9, 72), (0.02, 0.5, 0.03), tail())
    box('skirt', (100, 83), (1.6, 0.74, 0.03), dark())
    for x in (48, 156):
        box('cal', (x, 82), (0.1, 0.03, 0.07), mat('red', srgb('#e8323c'), rough=0.3), y=-0.3)
        for yy in (-1, 1):
            wheel(f'w{x}{yy}', (x, 88), 17, yy*0.3, 0.17, chrome())
    return [(48, 88, 17), (156, 88, 17)]

def car2():  # 노란 레이서 (포뮬러)
    m = paint('#ffc928', 'p2')
    d = 'M18 76 L40 66 L88 61 L98 48 Q100 46 104 46 L128 46 Q132 46 134 50 L142 62 L172 66 L196 76 L196 82 L18 84 Z'
    pts = path_points(d)
    H = 0.2
    slab('body', pts, H, m, bevel=0.04)
    slab('pods', path_points('M60 70 L130 66 L134 82 L60 84 Z'), 0.36, m, bevel=0.045)
    slab('podstripe', path_points('M62 70 L126 66 L132 80 L62 82 Z'), 0.004, dark(), bevel=0.003, y=-0.364)
    tube('ps', [(68, 74), (124, 71)], 0.008, m, -0.37)
    box('cockpit', (117, 54), (0.3, 0.2, 0.06), mat('liner', srgb('#0b0f1c'), rough=0.9), bev=0.02)
    sphere('helmet', (116, 39), 0.085, mat('red', srgb('#e8323c'), rough=0.25, coat=1.0))
    sphere('visor', (121, 38), 0.06, mat('visor', srgb('#1a2238'), rough=0.05, coat=1.0), y=-0.025, scale=(1, 1.3, 0.55))
    box('airbox', (100, 40), (0.12, 0.1, 0.12), dark(), bev=0.02)
    # 번호판
    cyl('numdisc', (84, 64), 0.075, 0.01, white(), y=-0.37)
    text('num', '1', (84, 64.5), 0.11, dark(), -0.378)
    # 뒷날개
    box('rwing', (18, 42), (0.3, 0.8, 0.07), dark(), bev=0.01)
    box('rwing2', (18, 40), (0.26, 0.82, 0.02), m, bev=0.006)
    for yy in (-0.38, 0.38):
        box('plate', (18, 44), (0.32, 0.015, 0.16), dark(), y=yy, bev=0.004)
    box('rpost', (10, 60), (0.05, 0.05, 0.36), dark())
    # 앞날개
    box('fwing', (186, 86), (0.24, 0.98, 0.025), dark(), bev=0.006)
    box('fwing2', (184, 83), (0.18, 0.96, 0.02), mat('red', srgb('#e8323c'), rough=0.25, coat=1.0), bev=0.005)
    for yy in (-0.48, 0.48):
        box('fplate', (186, 82), (0.24, 0.015, 0.1), dark(), y=yy, bev=0.004)
    for x, r in ((44, 20), (164, 20)):
        for yy in (-1, 1):
            wheel(f'w{x}{yy}', (x, 86), r, yy*0.38, 0.2, chrome())
            box('arm', (x, 80), (0.05, 0.36, 0.02), dark(), y=yy*0.2)
    return [(44, 86, 20), (164, 86, 20)]

def car3():  # 초록 랠리
    m = paint('#5cc423', 'p3')
    d = 'M10 84 L12 62 Q14 56 30 54 L54 52 L74 32 Q78 28 86 28 L136 28 Q142 28 146 32 L164 52 L186 56 Q194 58 194 66 L194 84 Z'
    pts = path_points(d)
    H = 0.4
    b = slab('body', pts, H, m, bevel=0.045)
    b = cut_wells(b, [((50, 88), 17), ((154, 88), 17)], H)
    for c in ((50, 88), (154, 88)):
        well_liner(c, 17, H)
    cabin(pts, 51, 31, H, m)
    for w in ('M80 34 L104 34 L104 51 L62 51 Z', 'M110 34 L136 34 L156 51 L110 51 Z'):
        slab('win', path_points(w), 0.004, glass(), bevel=0.003, y=-H - 0.004)
    slab('s1', path_points('M12 74 Q80 58 194 66 L194 73 Q92 66 12 82 Z'), 0.004, white(), bevel=0.003, y=-H - 0.005)
    slab('s2', path_points('M12 80 Q90 68 194 76 L194 79 Q92 72 12 84 Z'), 0.004, mat('orange', srgb('#ff8a1f'), rough=0.3, coat=1.0), bevel=0.003, y=-H - 0.006)
    cyl('numdisc', (106, 61), 0.1, 0.01, white(), y=-H - 0.012)
    text('num', '7', (106, 61.5), 0.14, dark(), -H - 0.02)
    box('lightbar', (108, 24.5), (0.46, 0.46, 0.05), dark())
    for k, x in enumerate((95, 108, 121)):
        cyl(f'rl{k}', (x, 24.5), 0.03, 0.03, amber(), y=-0.23)
    box('hl', (192, 61), (0.04, 0.12, 0.05), head(), y=-0.27)
    box('hl2', (192, 61), (0.04, 0.12, 0.05), head(), y=0.27)
    box('tl', (11, 65), (0.02, 0.1, 0.07), tail(), y=-0.3)
    box('skid', (196, 82), (0.05, 0.6, 0.05), chrome(), bev=0.01)
    for x in (74, 178):
        box('flap', (x, 88), (0.03, 0.14, 0.13), mat('red', srgb('#e8323c'), rough=0.5), y=-0.33)
    for x in (50, 154):
        for yy in (-1, 1):
            wheel(f'w{x}{yy}', (x, 88), 17, yy*0.34, 0.18, gold())
    return [(50, 88, 17), (154, 88, 17)]

def car4():  # 보라 머슬
    m = paint('#7a3fd6', 'p4')
    d = 'M6 84 L8 64 Q10 58 22 58 L50 56 L72 38 Q76 36 82 36 L124 36 Q130 36 134 40 L150 56 L184 58 Q194 60 194 70 L194 84 Z'
    pts = path_points(d)
    H = 0.42
    b = slab('body', pts, H, m, bevel=0.045)
    b = cut_wells(b, [((50, 88), 18), ((156, 88), 18)], H)
    for c in ((50, 88), (156, 88)):
        well_liner(c, 18, H)
    cabin(pts, 55, 39, H, m)
    for w in ('M78 41 L102 41 L102 55 L60 55 Z', 'M108 41 L128 41 L142 55 L108 55 Z'):
        slab('win', path_points(w), 0.004, glass(), bevel=0.003, y=-H - 0.004)
    tube('st1', [(9, 66), (193, 66)], 0.012, white(), -H - 0.008)
    tube('st2', [(9, 72), (193, 72)], 0.012, white(), -H - 0.008)
    # 위쪽 레이싱 줄무늬 (보닛·지붕·트렁크를 따라)
    top = [p for p in pts if p[1] < 60 and 10 < p[0] < 190]
    top.sort(key=lambda p: p[0])
    for yy in (-0.07, 0.07):
        tube('top', [(x, y - 4.2) for x, y in top], 0.03, white(), yy)
    box('scoop', (165, 54), (0.22, 0.22, 0.05), dark(), bev=0.015)
    box('fb', (195, 78), (0.06, 0.86, 0.06), chrome(), bev=0.02)
    box('rb', (5, 78), (0.06, 0.86, 0.06), chrome(), bev=0.02)
    cyl('hl', (192, 65), 0.035, 0.02, head(), y=-0.26, axis='X')
    cyl('hl2', (192, 65), 0.035, 0.02, head(), y=0.26, axis='X')
    box('tl', (7, 65), (0.02, 0.7, 0.04), tail())
    for yy in (-0.2, 0.2):
        cyl('pipe', (8, 84), 0.025, 0.12, chrome(), y=yy, axis='X')
    for x in (50, 156):
        for yy in (-1, 1):
            wheel(f'w{x}{yy}', (x, 88), 18, yy*0.36, 0.2, chrome())
    return [(50, 88, 18), (156, 88, 18)]

CARS = [car0, car1, car2, car3, car4]

# ---------- 장면 ----------
def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    MATS.clear()
    global GLASS
    GLASS = None
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.samples = SAMPLES
    sc.cycles.use_denoising = True
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        prefs.compute_device_type = 'HIP'
        prefs.get_devices()
        ok = False
        for dv in prefs.devices:
            dv.use = dv.type in ('HIP', 'CPU')
            ok = ok or dv.type == 'HIP'
        sc.cycles.device = 'GPU' if ok else 'CPU'
    except Exception:
        sc.cycles.device = 'CPU'
    sc.render.film_transparent = True
    sc.render.resolution_x = 750
    sc.render.resolution_y = 420
    sc.render.resolution_percentage = 100
    sc.view_settings.view_transform = 'Standard'
    sc.view_settings.look = 'None'
    # 스튜디오 하늘: 위는 밝게, 아래는 어둡게 (광택 반사용)
    w = bpy.data.worlds.new('studio')
    sc.world = w
    w.use_nodes = True
    nt = w.node_tree
    bg = nt.nodes['Background']
    tc = nt.nodes.new('ShaderNodeTexCoord')
    sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = 0.45
    ramp.color_ramp.elements[0].color = (0.05, 0.06, 0.08, 1)
    ramp.color_ramp.elements[1].position = 0.75
    ramp.color_ramp.elements[1].color = (0.55, 0.58, 0.62, 1)
    mr = nt.nodes.new('ShaderNodeMapRange')
    mr.inputs['From Min'].default_value = -1
    mr.inputs['From Max'].default_value = 1
    nt.links.new(tc.outputs['Generated'], sep.inputs[0])
    nt.links.new(sep.outputs['Z'], mr.inputs['Value'])
    nt.links.new(mr.outputs['Result'], ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], bg.inputs['Color'])
    bg.inputs['Strength'].default_value = 0.6

def lights():
    def area(name, loc, size, energy, color=(1, 1, 1)):
        ld = bpy.data.lights.new(name, 'AREA')
        ld.size = size; ld.energy = energy; ld.color = color
        ob = link(bpy.data.objects.new(name, ld))
        ob.location = loc
        d = Vector((0, 0, 0.5)) - Vector(loc)
        ob.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    area('key', (-1.5, -3.0, 3.5), 3.0, 420)
    area('fill', (3.5, -2.5, 1.2), 2.5, 110, (0.9, 0.95, 1.0))
    area('rim', (0.5, 3.5, 2.5), 3.0, 260)
    area('top', (0, 0, 4), 4.0, 140)

def camera():
    cd = bpy.data.cameras.new('cam')
    cd.type = 'ORTHO'
    cd.ortho_scale = 2.55
    ob = link(bpy.data.objects.new('cam', cd))
    target = Vector((0.04, 0, 0.42))
    yaw, pitch, dist = math.radians(28), math.radians(16), 8
    ob.location = target + Vector((math.sin(yaw)*math.cos(pitch), -math.cos(yaw)*math.cos(pitch), math.sin(pitch))) * dist
    ob.rotation_euler = (target - ob.location).to_track_quat('-Z', 'Y').to_euler()
    bpy.context.scene.camera = ob

def ground(z):
    bpy.ops.mesh.primitive_plane_add(size=8, location=(0, 0, z))
    pl = bpy.context.active_object
    pl.is_shadow_catcher = True

for idx in ONLY:
    reset()
    lights()
    camera()
    wh = CARS[idx]()
    zmin = min((112 - (cy + r)) / 100.0 for cx, cy, r in wh)
    ground(zmin)
    sc = bpy.context.scene
    try:
        sc.render.image_settings.file_format = 'WEBP'
        sc.render.image_settings.color_mode = 'RGBA'
        sc.render.image_settings.quality = 88
        ext = 'webp'
    except Exception:
        sc.render.image_settings.file_format = 'PNG'
        sc.render.image_settings.color_mode = 'RGBA'
        ext = 'png'
    sc.render.filepath = os.path.join(OUT, f'car{idx}.{ext}')
    bpy.ops.render.render(write_still=True)
    print('RENDERED', sc.render.filepath)
