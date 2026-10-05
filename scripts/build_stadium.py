"""Original Turning Point stadium. Run with Blender 5.2: blender -b -P scripts/build_stadium.py.

Produces a merged, material-batched GLB for the browser and an editable .blend source.
No imported artwork, stock geometry, tracked positions, or fixture data is used.
"""
from pathlib import Path
import math
import random
import bpy

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "frontend/public/assets"
SOURCE = ROOT / "assets"
OUTPUT.mkdir(parents=True, exist_ok=True)
SOURCE.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
random.seed(42)

def material(name, color, metallic=0.0, emission=0.0):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = 0.72
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Emission Color"].default_value = (*color, 1)
    bsdf.inputs["Emission Strength"].default_value = emission
    return m

materials = [
    material("Midnight concrete", (0.048, 0.074, 0.098)),
    material("Harbor seats", (0.028, 0.23, 0.34)),
    material("Vale seats", (0.36, 0.22, 0.035)),
    material("Neutral seats", (0.13, 0.20, 0.23)),
    material("Steel trusses", (0.23, 0.30, 0.34), 0.7),
    material("Ivory canopy", (0.47, 0.53, 0.53), 0.25),
    material("LED ribbon", (0.05, 0.78, 0.61), 0.1, 1.4),
    material("Floodlight lenses", (0.69, 0.88, 0.91), 0.1, 3.0),
    material("Spectators light", (0.37, 0.47, 0.49)),
    material("Spectators dark", (0.055, 0.11, 0.14)),
]
vertices, faces, indices = [], [], []

def box(x, y, z, w, d, h, mat):
    i = len(vertices)
    vertices.extend([(x+sx*w/2, y+sy*d/2, z+sz*h/2)
        for sx, sy, sz in [(-1,-1,-1),(-1,-1,1),(-1,1,-1),(-1,1,1),(1,-1,-1),(1,-1,1),(1,1,-1),(1,1,1)]])
    faces.extend([tuple(i+n for n in f) for f in [(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)]])
    indices.extend([mat]*6)

def outline(w, d, r, count=256):
    # Equal angular steps around a rounded rectangle; chairs are distributed on its perimeter.
    points=[]
    for i in range(count):
        a = i/count*math.tau
        sx, sy = math.cos(a), math.sin(a)
        points.append(((w/2-r)*(1 if sx >= 0 else -1)+r*sx,
                       (d/2-r)*(1 if sy >= 0 else -1)+r*sy))
    # Sample by length so straight stands have seats as well as rounded corners.
    corners=[]
    for cx,cy,start in [(w/2-r,d/2-r,0),(-w/2+r,d/2-r,90),(-w/2+r,-d/2+r,180),(w/2-r,-d/2+r,270)]:
        for j in range(17):
            a=math.radians(start+j*90/16)
            corners.append((cx+r*math.cos(a),cy+r*math.sin(a)))
    segments=[math.dist(corners[i],corners[(i+1)%len(corners)]) for i in range(len(corners))]
    total=sum(segments)
    for k in range(count):
        target=k*total/count
        for i,length in enumerate(segments):
            if target<=length:
                a,b=corners[i],corners[(i+1)%len(corners)]
                t=target/length
                points[k]=(a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t)
                break
            target-=length
    return points

box(0,0,-1.6,154,115,2.2,0)
box(0,0,-0.35,113,77,0.7,0)
for row in range(12):
    w,d=118+row*2.55,82+row*2.55
    inner,outer=outline(w,d,9),outline(w+2.55,d+2.55,10.25)
    level=.55+row*.9
    for n in range(len(inner)):
        k=(n+1)%len(inner)
        offset=len(vertices)
        vertices.extend([(inner[n][0],inner[n][1],level),(inner[k][0],inner[k][1],level),
                         (outer[k][0],outer[k][1],level),(outer[n][0],outer[n][1],level)])
        faces.append((offset,offset+1,offset+2,offset+3)); indices.append(0)
    for n,(x,y) in enumerate(outline(w+1.3,d+1.3,9.6,300)):
        if n%38 in (0,1,2):
            continue  # Aisles break up the continuous seating bowl.
        color=1 if x<0 else 2
        if n%7==0: color=3
        box(x,y,level+.16,.68,.68,.28,color)
        if random.random()<.82:
            box(x,y,level+.55,.37,.35,.48,8 if random.random()<.30 else 9)

# A roof over each long-side stand, with exposed batched steelwork.
for side in (-1,1):
    box(0,side*49.8,14.3,128,13,.4,5)
    box(0,side*44.1,13.45,126,.35,.35,4)
    for x in range(-60,61,10):
        box(x,side*54.0,6.9,.38,.38,14.0,4)
        box(x,side*49.8,13.7,.22,13,.22,4)
        box(x,side*44.0,12.95,3.2,.7,.45,7)
    box(0,side*38.0,.7,109,.3,1.15,6)
for side in (-1,1):
    box(side*56.0,0,.7,.3,73,1.15,6)
    # Minimal score-screen shell at each end, with no future match data.
    box(side*70.0,0,10.8,.45,14,6,0)
    box(side*69.7,0,10.8,.1,12.8,4.9,3)

mesh=bpy.data.meshes.new("Original stadium shell")
mesh.from_pydata(vertices,[],faces)
mesh.materials.clear()
for m in materials: mesh.materials.append(m)
mesh.update()
obj=bpy.data.objects.new("Turning Point Stadium",mesh)
bpy.context.collection.objects.link(obj)
for polygon,index in zip(mesh.polygons,indices): polygon.material_index=index
bpy.context.view_layer.objects.active=obj
obj.select_set(True)
bpy.ops.wm.save_as_mainfile(filepath=str(SOURCE / "turning-point-stadium.blend"))
bpy.ops.export_scene.gltf(filepath=str(OUTPUT / "turning-point-stadium.glb"),export_format="GLB",
    use_selection=True,export_yup=True,export_cameras=False,export_lights=False,export_extras=False)
print(f"TURNING_POINT_STADIUM vertices={len(vertices)} faces={len(faces)} bytes={(OUTPUT/'turning-point-stadium.glb').stat().st_size}")
