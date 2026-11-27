# 카 몬스터 레이스 자동차 5대를 Blender로 렌더링한다.
# 실행: & "D:\Blender\blender.exe" --background --factory-startup --python tools/blender_cars.py -- <출력폴더> [0 1 2 3 4] [--samples N]
# 결과: <출력폴더>/car0.webp ... car4.webp (750x420, 투명 배경, 바닥 그림자 포함)
# 좌표: 예전 SVG(200x112) 좌표를 그대로 쓴다. X = (x-100)/100, Z = (112-y)/100, 차 앞은 +X, 카메라 쪽 옆면은 -Y
# 실제 차종이나 다른 게임의 자동차를 따라 하지 않는 장난감 자동차 모양이다.
#
# 차체 만드는 법 (2026-11-27 개선): 옆모습 실루엣을 그냥 옆으로 밀면(예전 방식) 단면이 모두 같아서 각진 블록처럼 보인다.
# 그래서 실루엣을 앞에서 뒤까지 잘게 잘라, 자른 자리마다 둥근 단면(슈퍼타원)을 세우고 이어 붙인다(Loft).
#  - 코와 꽁무니는 폭이 좁아지고(tmin), 창문 위로는 지붕 쪽으로 좁아지고(roof), 바퀴 위는 펜더가 볼록하다(fender)
#  - 창문은 따로 붙이지 않고, 벨트라인(belt) 위 옆·앞·뒤 면에 유리 재질을 칠한다. pillars 구간은 차체색으로 남긴다
#  - 마지막에 Subdivision으로 매끈하게 다듬고, 바퀴 자리는 Boolean으로 판다
#  - 줄무늬·번호판 같은 장식은 Loft.sy()로 그 높이의 옆면 위치를 구해 표면에 붙인다
import bpy, bmesh, sys, math, os, re
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
    out = []
    for p in pts:
        if not out or abs(out[-1][0]-p[0]) + abs(out[-1][1]-p[1]) > 0.05:
            out.append(p)
    if len(out) > 2 and abs(out[0][0]-out[-1][0]) + abs(out[0][1]-out[-1][1]) < 0.05:
        out.pop()
    return out

def envelope(poly, x):
    """세로선 x가 실루엣과 만나는 가장 높은 점과 가장 낮은 점 (SVG y)."""
    ys = []
    n = len(poly)
    for k in range(n):
        (x1, y1), (x2, y2) = poly[k], poly[(k + 1) % n]
        if (x1 <= x < x2) or (x2 <= x < x1):
            t = (x - x1) / (x2 - x1)
            ys.append(y1 + t * (y2 - y1))
    if len(ys) < 2:
        return None
    return min(ys), max(ys)

def smooth(a, b, v):
    t = max(0.0, min(1.0, (v - a) / (b - a)))
    return t * t * (3 - 2 * t)

def P(x, y):
    return ((x - 100) / 100.0, (112 - y) / 100.0)

# ---------- 재질 ----------
MATS = {}
def mat(name, color, metal=0.0, rough=0.35, coat=0.0, emit=None, estr=0.0, grad=None, axis='Z'):
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
    if grad:  # 위는 밝게, 아래는 진하게 (오브젝트 좌표 기준)
        tc = nt.nodes.new('ShaderNodeTexCoord')
        sep = nt.nodes.new('ShaderNodeSeparateXYZ')
        mr = nt.nodes.new('ShaderNodeMapRange')
        mr.inputs['From Min'].default_value = grad[0]
        mr.inputs['From Max'].default_value = grad[1]
        ramp = nt.nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].color = (*grad[2], 1)
        ramp.color_ramp.elements[1].color = (*grad[3], 1)
        nt.links.new(tc.outputs['Object'], sep.inputs[0])
        nt.links.new(sep.outputs[axis], mr.inputs['Value'])
        nt.links.new(mr.outputs['Result'], ramp.inputs['Fac'])
        nt.links.new(ramp.outputs['Color'], bs.inputs['Base Color'])
    MATS[name] = m
    return m

def srgb(h):
    h = h.lstrip('#')
    c = [int(h[i:i+2], 16) / 255 for i in (0, 2, 4)]
    return tuple(((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92 for v in c)

def paint(hexc, name):
    return mat(name, srgb(hexc), metal=0.0, rough=0.3, coat=1.0)

def glass(): return mat('glass', srgb('#16233f'), rough=0.05, coat=1.0, grad=(0.4, 0.95, srgb('#0b1630'), srgb('#6fa6e0')), axis='Z')
def dark():   return mat('dark', srgb('#1d1f27'), rough=0.6)
def rubber(): return mat('rubber', srgb('#1a1c22'), rough=0.85)
def chrome(): return mat('chrome', srgb('#e6eaf0'), metal=1.0, rough=0.15)
def gold():   return mat('gold', srgb('#f2b92b'), metal=1.0, rough=0.22)
def white():  return mat('white', srgb('#f7f8fb'), rough=0.3, coat=1.0)
def head():   return mat('headlight', (1, 1, 0.9), rough=0.1, emit=(1, 0.97, 0.8), estr=6)
def tail():   return mat('taillight', srgb('#ff2b40'), rough=0.2, emit=srgb('#ff2b40'), estr=3)
def amber():  return mat('amber', srgb('#ffe98a'), rough=0.2, emit=srgb('#ffe98a'), estr=4)

def windowed(body_m, belt, pillars):
    """차체색 재질에 창문을 그려 넣는다: 벨트라인 위, 위를 보지 않는 면(옆·앞·뒤)은 유리. pillars 구간은 차체색.
    면 단위가 아니라 픽셀 단위로 나눠서 창문 테두리가 반듯하다."""
    name = body_m.name + '_win'
    if name in MATS:
        return MATS[name]
    src = body_m.node_tree.nodes['Principled BSDF']
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; N = nt.nodes; Lk = nt.links.new
    out = N['Material Output']; paint_bs = N['Principled BSDF']
    for k in ('Base Color', 'Metallic', 'Roughness', 'Coat Weight', 'Coat Roughness'):
        paint_bs.inputs[k].default_value = src.inputs[k].default_value
    gl = N.new('ShaderNodeBsdfPrincipled')
    gl.inputs['Base Color'].default_value = (*srgb('#0d1a33'), 1)
    gl.inputs['Roughness'].default_value = 0.08
    gl.inputs['Specular IOR Level'].default_value = 0.35
    mix = N.new('ShaderNodeMixShader')
    Lk(paint_bs.outputs[0], mix.inputs[1]); Lk(gl.outputs[0], mix.inputs[2]); Lk(mix.outputs[0], out.inputs['Surface'])

    def mr(val, a, b):  # a→0, b→1 (부드러운 계단)
        n = N.new('ShaderNodeMapRange'); n.interpolation_type = 'SMOOTHSTEP'
        n.inputs['From Min'].default_value = a; n.inputs['From Max'].default_value = b
        Lk(val, n.inputs['Value']); return n.outputs['Result']
    def mul(a, b):
        n = N.new('ShaderNodeMath'); n.operation = 'MULTIPLY'; Lk(a, n.inputs[0]); Lk(b, n.inputs[1]); return n.outputs[0]

    tc = N.new('ShaderNodeTexCoord'); sp = N.new('ShaderNodeSeparateXYZ'); Lk(tc.outputs['Object'], sp.inputs[0])
    geo = N.new('ShaderNodeNewGeometry'); sn = N.new('ShaderNodeSeparateXYZ'); Lk(geo.outputs['Normal'], sn.inputs[0])
    ab = N.new('ShaderNodeMath'); ab.operation = 'ABSOLUTE'; Lk(sn.outputs['Z'], ab.inputs[0])
    bz = (112 - belt) / 100.0
    mask = mul(mr(sp.outputs['Z'], bz, bz + 0.008), mr(ab.outputs[0], 0.8, 0.74))
    for a, b in pillars:
        xa, xb = (a - 100) / 100.0, (b - 100) / 100.0
        left = mr(sp.outputs['X'], xa + 0.004, xa)    # xa보다 왼쪽이면 1
        right = mr(sp.outputs['X'], xb - 0.004, xb)   # xb보다 오른쪽이면 1
        add = N.new('ShaderNodeMath'); add.operation = 'ADD'; add.use_clamp = True
        Lk(left, add.inputs[0]); Lk(right, add.inputs[1])
        mask = mul(mask, add.outputs[0])
    Lk(mask, mix.inputs[0])
    MATS[name] = m
    return m

# ---------- 도우미 ----------
def link(ob):
    bpy.context.scene.collection.objects.link(ob)
    return ob

class Loft:
    """옆모습 실루엣으로 둥근 차체를 만든다."""
    def __init__(s, d, half, belt=None, roof=0.74, wheels=(), pillars=(), tmin=0.68, fender=0.07, n=3.2, tlen=16, nb=7.0):
        s.poly = path_points(d)
        s.half, s.belt, s.roof, s.wheels, s.pillars = half, belt, roof, wheels, pillars
        s.tmin, s.fender, s.n, s.tlen, s.nb = tmin, fender, n, tlen, nb  # nb: 아랫부분은 거의 반듯하게 (차체 옆면이 아래로 곧게 떨어지게)
        s.cut = []
        s.x0 = min(p[0] for p in s.poly)
        s.x1 = max(p[0] for p in s.poly)

    def width(s, x, zs, top):
        w = s.half * (s.tmin + (1 - s.tmin) * smooth(0, s.tlen, min(x - s.x0, s.x1 - x)))
        if s.belt is not None and zs < s.belt and top < s.belt - 2:
            f = min(1.0, (s.belt - zs) / max(s.belt - top, 1e-3))
            w *= 1 - (1 - s.roof) * f
        else:
            for wx, wy, r in s.wheels:
                w *= 1 + s.fender * math.exp(-((x - wx) / (r * 1.25)) ** 2)
        return w

    def sy(s, x, zs):
        """SVG 점(x, zs) 높이에서 카메라 쪽 옆면의 Y (음수)."""
        e = envelope(s.poly, min(max(x, s.x0 + 0.3), s.x1 - 0.3))
        if not e:
            return -s.half
        top, bot = e
        zc, hz = (top + bot) / 2, max((bot - top) / 2, 1e-3)
        zz = max(-1.0, min(1.0, (zc - zs) / hz))
        n = s.n if zz >= 0 else s.nb
        sn = abs(zz) ** (n / 2)
        c = math.sqrt(max(0.0, 1 - sn * sn))
        return -s.width(x, zs, top) * c ** (2 / n)

    def arch_top(s, x):
        """바퀴 자리(판 곳) 위쪽 끝의 SVG y. 바퀴 자리 밖이면 무한대."""
        t = float('inf')
        for cx, cy, R in s.cut:
            if abs(x - cx) < R:
                t = min(t, cy - math.sqrt(R * R - (x - cx) ** 2))
        return t

    def build(s, name, body_m, N=72, M=36, subdiv=2):
        verts, faces, rings = [], [], []
        for k in range(N):
            u = k / (N - 1)
            x = s.x0 + 0.3 + (s.x1 - s.x0 - 0.6) * (1 - math.cos(math.pi * u)) / 2
            e = envelope(s.poly, x)
            if not e:
                continue
            top, bot = e
            zc, hz = (top + bot) / 2, (bot - top) / 2
            ring = []
            for j in range(M):
                th = 2 * math.pi * j / M - math.pi / 2
                c, sn = math.cos(th), math.sin(th)
                n = s.n if sn >= 0 else s.nb
                yy = math.copysign(abs(c) ** (2 / n), c)
                zz = math.copysign(abs(sn) ** (2 / n), sn)
                zs = zc - hz * zz
                X, Z = P(x, zs)
                ring.append(len(verts))
                verts.append((X, s.width(x, zs, top) * yy, Z))
            rings.append((x, zc, ring))
        for a in range(len(rings) - 1):
            r1, r2 = rings[a][2], rings[a + 1][2]
            for j in range(M):
                faces.append((r1[j], r1[(j + 1) % M], r2[(j + 1) % M], r2[j]))
        for (x, zc, ring), dx in ((rings[0], -0.004), (rings[-1], 0.004)):
            X, Z = P(x, zc)
            ci = len(verts); verts.append((X + dx, 0, Z))
            for j in range(M):
                faces.append((ring[j], ring[(j + 1) % M], ci))
        me = bpy.data.meshes.new(name)
        me.from_pydata(verts, [], faces)
        bm = bmesh.new(); bm.from_mesh(me)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(me); bm.free()
        ob = link(bpy.data.objects.new(name, me))
        me.materials.append(body_m if s.belt is None else windowed(body_m, s.belt, s.pillars))
        for p in me.polygons:
            p.use_smooth = True
        sd = ob.modifiers.new('sub', 'SUBSURF'); sd.levels = subdiv; sd.render_levels = subdiv
        s.ob = ob
        return ob

    def wells(s, wheel_list, extra=0.035):
        s.cut = [(c[0], c[1], r + extra * 100 - 0.5) for c, r in wheel_list]
        for k, (c, r) in enumerate(wheel_list):
            cut = cyl(f'cut{k}', c, r / 100.0 + extra, s.half * 3, dark())
            cut.hide_render = True; cut.hide_viewport = True
            b = s.ob.modifiers.new(f'well{k}', 'BOOLEAN'); b.object = cut; b.operation = 'DIFFERENCE'; b.solver = 'EXACT'
            cyl('liner', c, r / 100.0 + extra - 0.005, s.half * 1.7, mat('liner', srgb('#0b0f1c'), rough=0.9))

def decal(name, d, m, L, off=0.006, step=1.0):
    """옆면에 붙는 납작한 장식 (줄무늬, 공기구멍). 위아래 테두리를 따라 잘게 나눠 곡면에 맞춘다."""
    poly = path_points(d)
    x0, x1 = min(p[0] for p in poly) + 0.05, max(p[0] for p in poly) - 0.05
    verts, faces, rows = [], [], []
    x = x0
    while x <= x1 + 1e-6:
        e = envelope(poly, x)
        if e:
            top, bot = e
            bot = min(bot, L.arch_top(x))  # 바퀴 자리에서는 끊는다
            if bot - top < 0.3:
                if len(rows) > 1:
                    _decal_mesh(name, verts, rows, m)
                verts, rows = [], []
                x += step
                continue
            col = []
            for j in range(4):
                zs = top + (bot - top) * j / 3
                X, Z = P(x, zs)
                col.append(len(verts)); verts.append((X, L.sy(x, zs) - off, Z))
            rows.append(col)
        x += step
    if len(rows) > 1:
        _decal_mesh(name, verts, rows, m)

def _decal_mesh(name, verts, rows, m):
    faces = []
    for a in range(len(rows) - 1):
        for j in range(3):
            faces.append((rows[a][j], rows[a + 1][j], rows[a + 1][j + 1], rows[a][j + 1]))
    me = bpy.data.meshes.new(name); me.from_pydata(verts, [], faces)
    ob = link(bpy.data.objects.new(name, me)); me.materials.append(m)
    for p in me.polygons:
        p.use_smooth = True
    return ob

def tubes_cut(name, pts_svg, r, m, L, off):
    """옆면 줄을 바퀴 자리에서 끊어서 붙인다."""
    seg = []
    for p in pts_svg + [None]:
        if p is not None and p[1] < L.arch_top(p[0]) - r * 100:
            seg.append(p); continue
        if len(seg) > 1:
            tube(name, seg, r, m, lambda x, y: L.sy(x, y) - off)
        seg = []

def tube(name, pts_svg, r, m, y):
    """줄무늬·번개 같은 둥근 관. y는 숫자 또는 (x, y_svg) → Y 함수."""
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    cu.bevel_depth = r
    cu.bevel_resolution = 2
    cu.use_fill_caps = True
    sp = cu.splines.new('POLY')
    sp.points.add(len(pts_svg) - 1)
    for p, (xs, ys) in zip(sp.points, pts_svg):
        x, z = P(xs, ys)
        p.co = (x, y(xs, ys) if callable(y) else y, z, 1)
    ob = link(bpy.data.objects.new(name, cu))
    cu.materials.append(m)
    return ob

def dense(pts, step=2.0):
    """꺾은선 점을 잘게 나눠 곡면을 잘 따라가게 한다."""
    out = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(b[0]-a[0], b[1]-a[1]) / step))
        for k in range(1, n + 1):
            out.append((a[0] + (b[0]-a[0])*k/n, a[1] + (b[1]-a[1])*k/n))
    return out

def slab(name, pts_svg, half, m, bevel=0.03, y=0.0, res=3):
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
    x, z = P(*c_svg)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, segments=32, ring_count=16, location=(x, y, z))
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
    cyl(f'{tag}_tire', c_svg, R, width, rubber(), y=ycenter, bev=R*0.28 if not tread else R*0.2)
    if tread:  # 울퉁불퉁한 몬스터트럭 바퀴
        for k in range(18):
            a = k / 18 * 2 * math.pi
            bpy.ops.mesh.primitive_cube_add(size=1, location=(x + math.cos(a)*R*0.97, ycenter, z + math.sin(a)*R*0.97),
                                            rotation=(0, -a, 0))
            lug = bpy.context.active_object
            lug.scale = (R*0.12, width*0.9, R*0.2)
            lug.data.materials.append(rubber())
            bm = lug.modifiers.new('bev', 'BEVEL'); bm.width = 0.006; bm.segments = 2
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

def arch(name, c_svg, r, y, m, rad=0.022, a0=170, a1=10):
    """바퀴 위 펜더 테두리."""
    cx, cy = c_svg
    pts = [(cx + math.cos(math.radians(a)) * r, cy - math.sin(math.radians(a)) * r) for a in range(a0, a1 - 1, -10)]
    return tube(name, pts, rad, m, y)

# ---------- 자동차 5대 ----------
def car0():  # 강철 몬스터트럭
    m = mat('p0', srgb('#a3afc2'), metal=0.55, rough=0.28, coat=1.0)
    L = Loft('M12 66 L14 46 Q15 42 20 42 L58 40 L76 20 Q78 18 82 18 L130 18 Q134 18 136 20 L152 40 L186 42 Q192 43 192 50 L192 66 Z',
             0.42, belt=41, roof=0.8, pillars=[(104, 110)], tmin=0.74, fender=0.0, n=3.6)
    L.build('body', m)
    tube('stripe', dense([(18, 46), (60, 44)]), 0.008, white(), lambda x, y: L.sy(x, y) - 0.008)
    tube('stripe2', dense([(152, 44), (188, 46)]), 0.008, white(), lambda x, y: L.sy(x, y) - 0.008)
    # 몸통 아래 받침과 쇼크업소버
    box('frame', (100, 70), (1.3, 0.5, 0.08), dark())
    for x in (46, 154):
        for yy in (-0.22, 0.22):
            box('shock', (x, 72), (0.05, 0.05, 0.22), mat('orange', srgb('#ff8a1f'), metal=0.6, rough=0.3), y=yy, bev=0.008)
        for yy in (-1, 1):
            arch(f'flare{x}{yy}', (x, 84), 29, yy * 0.52, dark(), rad=0.035)
    # 지붕 조명
    box('lightbar', (106, 15), (0.46, 0.34, 0.06), dark(), y=0, bev=0.012)
    for k, x in enumerate((92, 101, 110, 119)):
        cyl(f'roofl{k}', (x, 15), 0.022, 0.02, amber(), y=-0.172)
    # 앞 범퍼, 헤드라이트, 꼬리등
    box('bumper', (195, 60), (0.06, 0.8, 0.12), chrome(), bev=0.02)
    for yy in (-0.2, 0.2):
        cyl('hl', (191, 48), 0.03, 0.04, head(), y=yy, axis='X')
        cyl('tl', (12, 50), 0.025, 0.04, tail(), y=yy, axis='X')
    for x in (46, 154):
        for yy in (-1, 1):
            wheel(f'w{x}{yy}', (x, 84), 24, yy*0.5, 0.3, chrome(), tread=True)
    return [(46, 84, 24), (154, 84, 24)]

def car1():  # 파란 번개 (슈퍼카)
    m = paint('#2563eb', 'p1')
    W = [(48, 88, 17), (156, 88, 17)]
    L = Loft('M8 84 C6 74 10 68 22 66 L58 60 C76 50 92 40 118 40 C138 40 152 48 166 58 L186 62 C194 64 197 72 195 84 Z',
             0.38, belt=59, roof=0.66, wheels=W, pillars=[(111, 117)], tmin=0.62, fender=0.09, n=2.8, tlen=22)
    L.build('body', m)
    L.wells([((48, 88), 17), ((156, 88), 17)])
    # 번개 줄무늬, 공기구멍
    tube('bolt', dense([(70, 67), (96, 63.5), (90, 69), (116, 65)], 1.5), 0.02, mat('yellow', srgb('#ffd84a'), rough=0.3, coat=1.0),
         lambda x, y: L.sy(x, y) - 0.012)
    decal('intake', 'M120 66 L152 63 L142 76 L124 76 Z', dark(), L)
    # 뒷날개
    box('wing', (16, 58), (0.16, 0.62, 0.022), mat('p1d', srgb('#0f2a78'), rough=0.3, coat=1.0), bev=0.008)
    for yy in (-0.2, 0.2):
        box('wpost', (18, 63), (0.03, 0.03, 0.08), dark(), y=yy, bev=0.004)
    for yy in (-0.2, 0.2):
        box('hl', (189, 66), (0.07, 0.13, 0.03), head(), y=yy, bev=0.01)
    box('tl', (9, 72), (0.03, 0.4, 0.03), tail(), bev=0.008)
    for x in (48, 156):
        box('cal', (x, 82), (0.1, 0.03, 0.07), mat('red', srgb('#e8323c'), rough=0.3), y=-0.3)
        for yy in (-1, 1):
            wheel(f'w{x}{yy}', (x, 88), 17, yy*0.32, 0.17, chrome())
    return W

def car2():  # 노란 레이서 (포뮬러)
    m = paint('#ffc928', 'p2')
    L = Loft('M18 76 L40 66 L88 61 L98 48 Q100 46 104 46 L128 46 Q132 46 134 50 L142 62 L172 66 L196 76 L196 82 L18 84 Z',
             0.17, tmin=0.45, n=2.6, tlen=40)
    L.build('body', m)
    pods = Loft('M60 70 L130 66 L134 82 L60 84 Z', 0.34, tmin=0.55, n=2.8, tlen=18)
    pods.build('pods', m)
    decal('podstripe', 'M66 71 L126 67.5 L130 79 L66 81 Z', dark(), pods)
    tube('ps', dense([(70, 74), (124, 71)]), 0.008, m, lambda x, y: pods.sy(x, y) - 0.012)
    box('cockpit', (117, 52), (0.3, 0.2, 0.06), mat('liner', srgb('#0b0f1c'), rough=0.9), bev=0.025)
    sphere('helmet', (116, 41), 0.085, mat('red', srgb('#e8323c'), rough=0.25, coat=1.0))
    sphere('visor', (121, 40), 0.06, mat('visor', srgb('#1a2238'), rough=0.05, coat=1.0), y=-0.025, scale=(1, 1.3, 0.55))
    box('airbox', (100, 42), (0.12, 0.1, 0.12), dark(), bev=0.03)
    # 번호판
    cyl('numdisc', (84, 74), 0.07, 0.01, white(), y=pods.sy(84, 74) - 0.008)
    text('num', '1', (84, 74.5), 0.1, dark(), pods.sy(84, 74) - 0.016)
    # 뒷날개
    box('rwing', (18, 42), (0.3, 0.8, 0.07), dark(), bev=0.015)
    box('rwing2', (18, 40), (0.26, 0.82, 0.02), m, bev=0.006)
    for yy in (-0.38, 0.38):
        box('plate', (18, 44), (0.32, 0.015, 0.16), dark(), y=yy, bev=0.004)
    box('rpost', (14, 60), (0.05, 0.05, 0.36), dark())
    # 앞날개
    box('fwing', (186, 86), (0.24, 0.98, 0.025), dark(), bev=0.008)
    box('fwing2', (184, 83), (0.18, 0.96, 0.02), mat('red', srgb('#e8323c'), rough=0.25, coat=1.0), bev=0.006)
    for yy in (-0.48, 0.48):
        box('fplate', (186, 82), (0.24, 0.015, 0.1), dark(), y=yy, bev=0.004)
    for x, r in ((44, 20), (164, 20)):
        for yy in (-1, 1):
            wheel(f'w{x}{yy}', (x, 86), r, yy*0.38, 0.2, chrome())
            box('arm', (x, 80), (0.05, 0.36, 0.02), dark(), y=yy*0.2)
    return [(44, 86, 20), (164, 86, 20)]

def car3():  # 초록 랠리
    m = paint('#5cc423', 'p3')
    W = [(50, 88, 17), (154, 88, 17)]
    L = Loft('M10 84 L12 62 Q14 56 30 54 L54 52 L74 32 Q78 28 86 28 L136 28 Q142 28 146 32 L164 52 L186 56 Q194 58 194 66 L194 84 Z',
             0.4, belt=52, roof=0.76, wheels=W, pillars=[(104, 110)], tmin=0.7, fender=0.09, n=3.2)
    L.build('body', m)
    L.wells([((50, 88), 17), ((154, 88), 17)])
    decal('s1', 'M12 74 Q80 58 194 66 L194 73 Q92 66 12 82 Z', white(), L)
    decal('s2', 'M12 80 Q90 68 194 76 L194 79 Q92 72 12 84 Z', mat('orange', srgb('#ff8a1f'), rough=0.3, coat=1.0), L, off=0.007)
    cyl('numdisc', (106, 62), 0.1, 0.01, white(), y=L.sy(106, 62) - 0.01)
    text('num', '7', (106, 62.5), 0.14, dark(), L.sy(106, 62) - 0.018)
    box('lightbar', (108, 24.5), (0.46, 0.46, 0.05), dark(), bev=0.012)
    for k, x in enumerate((95, 108, 121)):
        cyl(f'rl{k}', (x, 24.5), 0.03, 0.03, amber(), y=-0.23)
    for yy in (-0.2, 0.2):
        cyl('hl', (193, 61), 0.03, 0.03, head(), y=yy, axis='X')
        cyl('tl', (11, 63), 0.025, 0.03, tail(), y=yy, axis='X')
    box('skid', (196, 82), (0.05, 0.5, 0.05), chrome(), bev=0.012)
    for x in (74, 178):
        box('flap', (x, 90), (0.03, 0.14, 0.13), mat('red', srgb('#e8323c'), rough=0.5), y=-0.33, bev=0.008)
    for x in (50, 154):
        for yy in (-1, 1):
            wheel(f'w{x}{yy}', (x, 88), 17, yy*0.34, 0.18, gold())
    return W

def car4():  # 보라 머슬
    m = paint('#7a3fd6', 'p4')
    W = [(50, 88, 18), (156, 88, 18)]
    L = Loft('M6 84 L8 64 Q10 58 22 58 L50 56 L72 38 Q76 36 82 36 L124 36 Q130 36 134 40 L150 56 L184 58 Q194 60 194 70 L194 84 Z',
             0.42, belt=56, roof=0.74, wheels=W, pillars=[(102, 108)], tmin=0.72, fender=0.08, n=3.4)
    L.build('body', m)
    L.wells([((50, 88), 18), ((156, 88), 18)])
    tubes_cut('st1', dense([(9, 66), (193, 66)]), 0.012, white(), L, 0.01)
    tubes_cut('st2', dense([(9, 72), (193, 72)]), 0.012, white(), L, 0.01)
    # 위쪽 레이싱 줄무늬 (보닛·지붕·트렁크를 따라)
    # 트렁크, 지붕, 보닛에만 (앞유리·뒷유리 위는 건너뛴다)
    for a, b in ((10, 68), (86, 128), (154, 190)):
        tops = [(x, envelope(L.poly, x)[0] + 1.3) for x in range(a, b + 1, 2)]
        for yy in (-0.065, 0.065):
            tube('top', tops, 0.02, white(), yy)
    box('scoop', (165, 55), (0.22, 0.2, 0.05), dark(), bev=0.02)
    box('fb', (195, 78), (0.06, 0.7, 0.06), chrome(), bev=0.025)
    box('rb', (5, 78), (0.06, 0.7, 0.06), chrome(), bev=0.025)
    for yy in (-0.2, 0.2):
        cyl('hl', (193, 65), 0.035, 0.03, head(), y=yy, axis='X')
    box('tl', (7, 64), (0.03, 0.5, 0.04), tail(), bev=0.01)
    for yy in (-0.16, 0.16):
        cyl('pipe', (6, 84), 0.025, 0.12, chrome(), y=yy, axis='X')
    for x in (50, 156):
        for yy in (-1, 1):
            wheel(f'w{x}{yy}', (x, 88), 18, yy*0.37, 0.2, chrome())
    return W

CARS = [car0, car1, car2, car3, car4]

# ---------- 장면 ----------
def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    MATS.clear()
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
    # 색을 선명하게 두려고 Standard. 대신 조명을 낮춰 밝은 곳이 하얗게 날아가지 않게 한다 (AgX는 색이 파스텔처럼 흐려졌다)
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
    bg.inputs['Strength'].default_value = 0.5

def lights():
    def area(name, loc, size, energy, color=(1, 1, 1)):
        ld = bpy.data.lights.new(name, 'AREA')
        ld.size = size; ld.energy = energy; ld.color = color
        ob = link(bpy.data.objects.new(name, ld))
        ob.location = loc
        d = Vector((0, 0, 0.5)) - Vector(loc)
        ob.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    area('key', (-1.5, -3.0, 3.5), 3.0, 300)
    area('fill', (3.5, -2.5, 1.2), 2.5, 110, (0.9, 0.95, 1.0))
    area('rim', (0.5, 3.5, 2.5), 3.0, 220)
    area('top', (0, 0, 4), 4.0, 80)

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
    print('RENDERED', sc.render.filepath, 'view', sc.view_settings.view_transform)
