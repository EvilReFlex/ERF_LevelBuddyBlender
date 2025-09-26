#  ***** BEGIN GPL LICENSE BLOCK *****
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#  ***** END GPL LICENSE BLOCK *****

from copy import copy
import math
import bpy
import bmesh
from mathutils import Matrix, Vector

bl_info = {
    "name": "ERF Level Buddy",
    "author": "Matt Lucas, HickVieira, EvilReFlex",
    "version": (2, 4),
    "blender": (4, 0, 0),
    "location": "View3D > Tools > Level Buddy",
    "description": "Workflow tools inspired by Doom and Unreal level mapping.",
    "warning": "WIP",
    "wiki_url": "https://github.com/hickVieira/LevelBuddyBlender3",
    "category": "Object",
}

IS_4X = bpy.app.version >= (4, 0, 0)
PREFERRED_COLOR_ATTR_NAME = "Attribute"

# =========================
# helpers
# =========================

def translate(val, t): return val + t
def scale(val, s): return val * s

def rotate2D(uv, degrees):
    radians = math.radians(degrees)
    newUV = copy(uv)
    newUV.x = uv.x * math.cos(radians) - uv.y * math.sin(radians)
    newUV.y = uv.x * math.sin(radians) + uv.y * math.cos(radians)
    return newUV

def _get_attr_name():
    scn = bpy.context.scene
    return getattr(scn, "color_attribute_name", "") or PREFERRED_COLOR_ATTR_NAME

def _activate_render_attr_40(mesh, layer):
    for attr in ("active_color", "render_color"):
        try:
            setattr(mesh.color_attributes, attr, layer)
        except Exception:
            pass
    try:
        idx = list(mesh.color_attributes).index(layer)
        mesh.color_attributes.active_color_index = idx
        mesh.color_attributes.render_color_index = idx
    except Exception:
        pass

def ensure_color_layer(mesh, prefer_name=None):
    """Ensure per-corner Color-Attribut existiert und ist aktiv/render-aktiv."""
    if prefer_name is None:
        prefer_name = _get_attr_name()

    if hasattr(mesh, "color_attributes"):
        layer = mesh.color_attributes.get(prefer_name) \
            or mesh.color_attributes.get("Col") \
            or mesh.color_attributes.get("Color")
        if layer is None:
            layer = mesh.color_attributes.new(
                name=prefer_name, domain='CORNER', type='BYTE_COLOR'
            )
        _activate_render_attr_40(mesh, layer)
        return layer
    else:
        layer = None
        if mesh.vertex_colors:
            if prefer_name in mesh.vertex_colors:
                layer = mesh.vertex_colors[prefer_name]
            elif "Col" in mesh.vertex_colors:
                layer = mesh.vertex_colors["Col"]
            elif "Color" in mesh.vertex_colors:
                layer = mesh.vertex_colors["Color"]
            else:
                layer = mesh.vertex_colors.active
        if layer is None:
            layer = mesh.vertex_colors.new(name=prefer_name)
        try:
            mesh.vertex_colors.active = layer
        except Exception:
            pass
        return layer

def fill_color_layer_object_mode(obj, rgba):
    """Komplettes Color-Attribut mit RGBA füllen (Object Mode, foreach_set)."""
    mesh = obj.data
    prev_mode = obj.mode
    if prev_mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    if hasattr(mesh, "color_attributes"):
        layer = ensure_color_layer(mesh)
        data = layer.data
        n = len(data)
        if n > 0:
            flat = [rgba[0], rgba[1], rgba[2], rgba[3]] * n
            data.foreach_set("color", flat)
    else:
        layer = ensure_color_layer(mesh)
        loop_count = len(mesh.loops)
        if loop_count > 0:
            flat = [rgba[0], rgba[1], rgba[2], rgba[3]] * loop_count
            layer.data.foreach_set("color", flat)

    try:
        mesh.update()
        obj.data.update()
    except Exception:
        pass

    if prev_mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode=prev_mode)
        except Exception:
            pass

# ---------- Boolean robustness helpers ----------

def _prep_boolean_mesh(me, merge_dist=1e-6):
    """Triangulate & remove doubles on a mesh (in-place) to stabilize booleans."""
    bm = bmesh.new()
    bm.from_mesh(me)
    try:
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=merge_dist)
        bm.normal_update()
    finally:
        bm.to_mesh(me)
        bm.free()

def _cleanup_result_mesh(me, merge_dist=1e-5, angle_limit=0.0):
    """Merge-by-distance; optional dissolve by angle."""
    bm = bmesh.new()
    bm.from_mesh(me)
    try:
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=merge_dist)
        if angle_limit > 0.0:
            bmesh.ops.dissolve_limit(
                bm, angle_limit=math.radians(angle_limit),
                verts=bm.verts[:], edges=bm.edges[:]
            )
        bm.normal_update()
    finally:
        bm.to_mesh(me)
        bm.free()

# ---------- World-space snap helpers ----------

def snap_object_mesh_world(obj, step=0.01):
    """Snap all verts of obj.data to a world-space grid with given step."""
    if step <= 0.0 or obj.type != 'MESH':
        return 0
    mesh = obj.data
    mw = obj.matrix_world
    imw = mw.inverted_safe()
    bm = bmesh.new()
    bm.from_mesh(mesh)
    changed = 0
    for v in bm.verts:
        wco = mw @ v.co
        wco.x = round(wco.x / step) * step
        wco.y = round(wco.y / step) * step
        wco.z = round(wco.z / step) * step
        new_local = imw @ wco
        if (new_local - v.co).length > 1e-9:
            v.co = new_local
            changed += 1
    bm.to_mesh(mesh)
    bm.free()
    try:
        mesh.update()
    except Exception:
        pass
    return changed

# =========================
# core functionality
# =========================

def auto_texture(bool_obj, source_obj):
    mesh = bool_obj.data
    objectLocation = source_obj.location
    objectScale = source_obj.scale

    bm = bmesh.new()
    bm.from_mesh(mesh)
    uv_layer = bm.loops.layers.uv.verify()

    for f in bm.faces:
        nX, nY, nZ = abs(f.normal.x), abs(f.normal.y), abs(f.normal.z)
        faceDirection = "x"
        faceNormalLargest = nX
        if faceNormalLargest < nY: faceNormalLargest, faceDirection = nY, "y"
        if faceNormalLargest < nZ: faceNormalLargest, faceDirection = nZ, "z"
        if faceDirection == "x" and f.normal.x < 0: faceDirection = "-x"
        if faceDirection == "y" and f.normal.y < 0: faceDirection = "-y"
        if faceDirection == "z" and f.normal.z < 0: faceDirection = "-z"

        for l in f.loops:
            luv = l[uv_layer]
            if faceDirection in ("x", "-x"):
                luv.uv.x = (l.vert.co.y * objectScale[1]) + objectLocation[1]
                luv.uv.y = (l.vert.co.z * objectScale[2]) + objectLocation[2]
                luv.uv = rotate2D(luv.uv, source_obj.wall_texture_rotation)
                luv.uv.x = translate(scale(luv.uv.x, source_obj.wall_texture_scale_offset[0]), source_obj.wall_texture_scale_offset[2])
                luv.uv.y = translate(scale(luv.uv.y, source_obj.wall_texture_scale_offset[1]), source_obj.wall_texture_scale_offset[3])
            if faceDirection in ("y", "-y"):
                luv.uv.x = (l.vert.co.x * objectScale[0]) + objectLocation[0]
                luv.uv.y = (l.vert.co.z * objectScale[2]) + objectLocation[2]
                luv.uv = rotate2D(luv.uv, source_obj.wall_texture_rotation)
                luv.uv.x = translate(scale(luv.uv.x, source_obj.wall_texture_scale_offset[0]), source_obj.wall_texture_scale_offset[2])
                luv.uv.y = translate(scale(luv.uv.y, source_obj.wall_texture_scale_offset[1]), source_obj.wall_texture_scale_offset[3])
            if faceDirection == "z":
                luv.uv.x = (l.vert.co.x * objectScale[0]) + objectLocation[0]
                luv.uv.y = (l.vert.co.y * objectScale[1]) + objectLocation[1]
                luv.uv = rotate2D(luv.uv, source_obj.ceiling_texture_rotation)
                luv.uv.x = translate(scale(luv.uv.x, source_obj.ceiling_texture_scale_offset[0]), source_obj.ceiling_texture_scale_offset[2])
                luv.uv.y = translate(scale(luv.uv.y, source_obj.ceiling_texture_scale_offset[1]), source_obj.ceiling_texture_scale_offset[3])
            if faceDirection == "-z":
                luv.uv.x = (l.vert.co.x * objectScale[0]) + objectLocation[0]
                luv.uv.y = (l.vert.co.y * objectScale[1]) + objectLocation[1]
                luv.uv = rotate2D(luv.uv, source_obj.floor_texture_rotation)
                luv.uv.x = translate(scale(luv.uv.x, source_obj.floor_texture_scale_offset[0]), source_obj.floor_texture_scale_offset[2])
                luv.uv.y = translate(scale(luv.uv.y, source_obj.floor_texture_scale_offset[1]), source_obj.floor_texture_scale_offset[3])
    bm.to_mesh(mesh)
    bm.free()
    bool_obj.data = mesh

def update_location_precision(ob):
    p = bpy.context.scene.map_precision
    ob.location.x = round(ob.location.x, p)
    ob.location.y = round(ob.location.y, p)
    ob.location.z = round(ob.location.z, p)
    cleanup_vertex_precision(ob)

def _update_sector_solidify(self, context):
    ob = context.active_object
    if ob and ob.modifiers:
        mod = ob.modifiers[0]
        if mod and mod.type == 'SOLIDIFY':
            mod.thickness = ob.ceiling_height - ob.floor_height
            if mod.thickness != 0:
                mod.offset = 1 + ob.floor_height / (mod.thickness / 2)

def update_brush_sector_modifier(ob):
    if ob.brush_type == 'BRUSH':
        for mod in list(ob.modifiers):
            if mod.type == 'SOLIDIFY':
                ob.modifiers.remove(mod)
        return
    has_solidify = any(m.type == 'SOLIDIFY' for m in ob.modifiers)
    if not has_solidify:
        bpy.ops.object.modifier_add(type='SOLIDIFY')
    for mod in ob.modifiers:
        if mod.type == 'SOLIDIFY':
            mod.use_even_offset = True
            try: mod.use_quality_normals = True
            except Exception: pass
            mod.thickness = ob.ceiling_height - ob.floor_height
            if mod.thickness != 0:
                mod.offset = 1 + ob.floor_height / (mod.thickness / 2)
            mod.material_offset = 1
            mod.material_offset_rim = 2
            break

def update_sector_materials(ob):
    while len(ob.material_slots) < 3:
        bpy.ops.object.material_slot_add()
    while len(ob.material_slots) > 3:
        bpy.ops.object.material_slot_remove()
    if bpy.data.materials.find(ob.ceiling_texture) != -1:
        ob.material_slots[0].material = bpy.data.materials[ob.ceiling_texture]
    if bpy.data.materials.find(ob.floor_texture) != -1:
        ob.material_slots[1].material = bpy.data.materials[ob.floor_texture]
    if bpy.data.materials.find(ob.wall_texture) != -1:
        ob.material_slots[2].material = bpy.data.materials[ob.wall_texture]

def update_brush_material(ob):
    while len(ob.material_slots) < 1:
        bpy.ops.object.material_slot_add()
    while len(ob.material_slots) > 1:
        bpy.ops.object.material_slot_remove()
    mat_name = getattr(ob, "brush_material", "") or ""
    if mat_name and bpy.data.materials.find(mat_name) != -1:
        ob.material_slots[0].material = bpy.data.materials[mat_name]
    else:
        ob.material_slots[0].material = None

def update_brush(obj):
    bpy.context.view_layer.objects.active = obj
    if obj:
        obj.display_type = 'WIRE'
        update_brush_sector_modifier(obj)
        if obj.brush_type == 'SECTOR':
            update_sector_materials(obj)
        elif obj.brush_type == 'BRUSH':
            update_brush_material(obj)
        update_location_precision(obj)

def cleanup_vertex_precision(ob):
    p = bpy.context.scene.map_precision
    for v in ob.data.vertices:
        v.co.x = round(v.co.x, p)
        v.co.y = round(v.co.y, p)
        v.co.z = round(v.co.z, p)

def apply_csg(target, source_obj, bool_obj, reporter=None):
    # ensure color attrs
    if target.data: ensure_color_layer(target.data)
    if bool_obj.data: ensure_color_layer(bool_obj.data)

    bpy.ops.object.select_all(action='DESELECT')
    target.select_set(True)
    copy_materials(target, source_obj)

    # Boolean modifier with robustness tweaks
    mod = target.modifiers.new(name=source_obj.name, type='BOOLEAN')
    mod.object = bool_obj
    mod.operation = csg_operation_to_blender_boolean[source_obj.csg_operation]
    mod.solver = 'EXACT'
    if hasattr(mod, "double_threshold"):
        mod.double_threshold = 1e-6

    try:
        bpy.ops.object.modifier_apply(modifier=source_obj.name)
    except Exception as e:
        if reporter:
            reporter.report({'WARNING'}, f"Boolean apply failed on {target.name}: {e}")
        try:
            target.modifiers.remove(mod)
        except Exception:
            pass

def build_bool_object(sourceObj):
    bpy.ops.object.select_all(action='DESELECT')
    sourceObj.select_set(True)

    dg = bpy.context.evaluated_depsgraph_get()
    eval_obj = sourceObj.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(eval_obj)

    # optional small overlap push
    scn = bpy.context.scene
    eps = scn.boolean_overlap_epsilon if scn.use_boolean_overlap else 0.0
    if eps and eps != 0.0:
        for v in me.vertices:
            v.co *= (1.0 + eps)

    if me is not None:
        _prep_boolean_mesh(me, merge_dist=1e-6)
        ensure_color_layer(me)

    ob_bool = bpy.data.objects.new("_booley", me)
    copy_transforms(ob_bool, sourceObj)
    cleanup_vertex_precision(ob_bool)
    return ob_bool

def create_new_boolean_object(scn, name):
    old_map = None
    if bpy.data.meshes.get(name + "_MESH") is not None:
        old_map = bpy.data.meshes[name + "_MESH"]; old_map.name = "map_old"
    me = bpy.data.meshes.new(name + "_MESH")
    if bpy.data.objects.get(name) is None:
        ob = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(ob)
    else:
        ob = bpy.data.objects[name]; ob.data = me
    if old_map is not None:
        bpy.data.meshes.remove(old_map)
    ob.select_set(True)
    return ob

def copy_materials(target, source):
    if not source.data or source.data.materials is None:
        return
    for sourceMaterial in source.data.materials:
        if sourceMaterial and sourceMaterial.name not in target.data.materials:
            target.data.materials.append(sourceMaterial)

def copy_transforms(a, b):
    a.location = b.location
    a.scale = b.scale
    a.rotation_euler = b.rotation_euler

def set_normals_inward(ob):
    try:
        bpy.ops.object.select_all(action='DESELECT')
        ob.select_set(True)
        bpy.context.view_layer.objects.active = ob
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.normals_make_consistent(inside=True)
        bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        try:
            bpy.ops.mesh.flip_normals()
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass

def remove_material(obj):
    scn = bpy.context.scene
    name = (getattr(scn, "remove_material", "") or "").strip()
    if not name: return
    i, remove = 0, False
    for m in obj.material_slots:
        if m.name == name: remove = True
        else:
            if not remove: i += 1
    if remove:
        obj.active_material_index = i
        bpy.ops.object.editmode_toggle()
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.object.material_slot_select()
        bpy.ops.mesh.delete(type='FACE')
        bpy.ops.object.editmode_toggle()
        bpy.ops.object.material_slot_remove()

# =========================
# properties
# =========================

bpy.types.Scene.map_precision = bpy.props.IntProperty(
    name="Map Precision", default=3, min=0, max=6,
    description="Rounding level of vertex precision"
)
bpy.types.Scene.map_use_auto_smooth = bpy.props.BoolProperty(
    name="Map Auto Smooth", description="Use auto smooth", default=True,
)
bpy.types.Scene.map_auto_smooth_angle = bpy.props.FloatProperty(
    name="Angle", description="Auto smooth angle",
    default=30, min=0, max=180, step=1, precision=0,
)
bpy.types.Scene.remove_material = bpy.props.StringProperty(
    name="Remove Material",
    description="Faces with this material will be removed on build"
)
bpy.types.Scene.color_attribute_name = bpy.props.StringProperty(
    name="Color Attribute Name",
    description="Per-corner color attribute to use",
    default=PREFERRED_COLOR_ATTR_NAME
)

# Boolean Overlap control (default ON with 0.002)
bpy.types.Scene.use_boolean_overlap = bpy.props.BoolProperty(
    name="Use Boolean Overlap", default=True,
    description="If enabled, operands are slightly expanded to ensure overlap for booleans"
)
bpy.types.Scene.boolean_overlap_epsilon = bpy.props.FloatProperty(
    name="Overlap Epsilon",
    description="Tiny uniform scale on boolean operands before operations. Set 0 to disable.",
    default=0.002, min=0.0, max=0.01, precision=5, step=0.0001
)

# Post-build snap control (default ON, 0.01 world grid)
bpy.types.Scene.post_build_snap_enable = bpy.props.BoolProperty(
    name="Post-Build Snap", default=True,
    description="Snap final LevelGeometry to a world grid after booleans"
)
bpy.types.Scene.post_build_snap_step = bpy.props.FloatProperty(
    name="Snap Step",
    description="World grid step for post-build snap",
    default=0.01, min=0.0001, max=10.0, precision=4
)

# UV/Height etc.
bpy.types.Object.ceiling_texture_scale_offset = bpy.props.FloatVectorProperty(
    name="Ceiling Texture Scale Offset", default=(1, 1, 0, 0),
    min=0, step=10, precision=3, size=4
)
bpy.types.Object.wall_texture_scale_offset = bpy.props.FloatVectorProperty(
    name="Wall Texture Scale Offset", default=(1, 1, 0, 0),
    min=0, step=10, precision=3, size=4
)
bpy.types.Object.floor_texture_scale_offset = bpy.props.FloatVectorProperty(
    name="Floor Texture Scale Offset", default=(1, 1, 0, 0),
    min=0, step=10, precision=3, size=4
)
bpy.types.Object.ceiling_texture_rotation = bpy.props.FloatProperty(
    name="Ceiling Texture Rotation", default=0, min=0, step=10, precision=3,
)
bpy.types.Object.wall_texture_rotation = bpy.props.FloatProperty(
    name="Wall Texture Rotation", default=0, min=0, step=10, precision=3,
)
bpy.types.Object.floor_texture_rotation = bpy.props.FloatProperty(
    name="Floor Texture Rotation", default=0, min=0, step=10, precision=3,
)
bpy.types.Object.ceiling_height = bpy.props.FloatProperty(
    name="Ceiling Height", default=4, step=10, precision=3, update=_update_sector_solidify
)
bpy.types.Object.floor_height = bpy.props.FloatProperty(
    name="Floor Height", default=0, step=10, precision=3, update=_update_sector_solidify
)
bpy.types.Object.floor_texture = bpy.props.StringProperty(name="Floor Texture")
bpy.types.Object.wall_texture = bpy.props.StringProperty(name="Wall Texture")
bpy.types.Object.ceiling_texture = bpy.props.StringProperty(name="Ceiling Texture")

bpy.types.Object.brush_type = bpy.props.EnumProperty(
    items=[("BRUSH", "Brush", "is a brush"),
           ("SECTOR", "Sector", "is a sector"),
           ("NONE", "None", "none")],
    name="Brush Type", description="the brush type", default='NONE'
)

# UI labels swapped, behavior unchanged:
# ADD (UNION) is shown as "Subtract", SUBTRACT (DIFFERENCE) is shown as "Add".
bpy.types.Object.csg_operation = bpy.props.EnumProperty(
    items=[
        ("ADD", "Subtract", "Boolean UNION (label swapped)"),
        ("SUBTRACT", "Add", "Boolean DIFFERENCE (label swapped)")
    ],
    name="CSG Op",
    description="Boolean operation (labels swapped by request)",
    default='ADD'
)

# mapping restored to original behavior
csg_operation_to_blender_boolean = {"ADD": "UNION", "SUBTRACT": "DIFFERENCE"}

bpy.types.Object.csg_order = bpy.props.IntProperty(
    name="CSG Order", default=0, description="Controls the order of CSG operation of the object"
)
bpy.types.Object.brush_auto_texture = bpy.props.BoolProperty(
    name="Brush Auto Texture", default=True, description="Auto Texture on or off"
)
bpy.types.Object.brush_material = bpy.props.StringProperty(
    name="Brush Material", description="Material used by Brush objects (copied into the built geometry)"
)

# Color Attribute UI
bpy.types.Scene.color_picker = bpy.props.FloatVectorProperty(
    name="Active", subtype='COLOR', default=(1.0, 1.0, 1.0), min=0.0, max=1.0
)

# =========================
# UI helpers
# =========================

def draw_uv_box(parent, obj, prop_name, label, rot_prop_name, rot_label="Rotation"):
    box = parent.box(); col = box.column(align=True)
    col.label(text=label)
    row = col.row(align=True); row.label(text="Scale")
    sub = row.row(align=True); sub.prop(obj, prop_name, index=0, text="U"); sub.prop(obj, prop_name, index=1, text="V")
    row2 = col.row(align=True); row2.label(text="Shift")
    sub2 = row2.row(align=True); sub2.prop(obj, prop_name, index=2, text="U"); sub2.prop(obj, prop_name, index=3, text="V")
    row3 = col.row(align=True); row3.label(text=rot_label); row3.prop(obj, rot_prop_name, text="°")

# =========================
# UI Panels
# =========================

class LevelBuddyPanel(bpy.types.Panel):
    bl_label = "Level Buddy"
    bl_space_type = "VIEW_3D"
    bl_region_type = 'UI'
    bl_category = 'Level Buddy'
    def draw(self, context):
        ob = context.active_object
        scn = bpy.context.scene
        layout = self.layout
        mode = context.mode

        col = layout.column(align=True)
        col.label(icon="WORLD", text="Map Settings")
        col.prop(scn, "map_precision")
        row = col.row(align=True)
        row.prop(scn, "map_use_auto_smooth", text="Auto Smooth")
        row.prop(scn, "map_auto_smooth_angle", text="Angle")
        col.prop_search(scn, "remove_material", bpy.data, "materials"); col.separator()
        col.prop(scn, "color_attribute_name")

        box = layout.box()
        box.label(text="Boolean Stability")
        rowb = box.row(align=True)
        rowb.prop(scn, "use_boolean_overlap", text="Use Boolean Overlap")
        rowb.prop(scn, "boolean_overlap_epsilon", text="Epsilon")

        box2 = layout.box()
        box2.label(text="Post-Build Snap")
        rowp = box2.row(align=True)
        rowp.prop(scn, "post_build_snap_enable", text="Enable")
        rowp.prop(scn, "post_build_snap_step", text="Step")

        col = layout.column(align=True)
        col.operator("scene.level_buddy_build_map", text="Build Map", icon="MOD_BUILD").bool_op = "UNION"

        if mode == 'OBJECT':
            col = layout.column(align=True)
            col.label(icon="SNAP_PEEL_OBJECT", text="Tools")
            row = col.row(align=True)
            op1 = row.operator("scene.level_buddy_new_geometry", text="New Sector", icon="MESH_PLANE"); op1.brush_type = 'SECTOR'
            op2 = row.operator("scene.level_buddy_new_geometry", text="New Brush", icon="CUBE"); op2.brush_type = 'BRUSH'

        if ob is not None and len(bpy.context.selected_objects) > 0:
            col = layout.column(align=True)
            col.label(icon="MOD_ARRAY", text="Brush Properties")
            typ = getattr(ob, "brush_type", "NONE")
            col.label(text=f"Type: {typ.title() if isinstance(typ, str) else str(typ)}")
            col.prop(ob, "csg_operation", text="CSG Op")
            col.prop(ob, "csg_order", text="CSG Order")
            col.prop(ob, "brush_auto_texture", text="Auto Texture")

            if ob.brush_auto_texture:
                draw_uv_box(col, ob, "ceiling_texture_scale_offset", "Ceiling UV", "ceiling_texture_rotation")
                draw_uv_box(col, ob, "wall_texture_scale_offset", "Wall UV", "wall_texture_rotation")
                draw_uv_box(col, ob, "floor_texture_scale_offset", "Floor UV", "floor_texture_rotation")

            if getattr(ob, "brush_type", 'NONE') == 'SECTOR':
                sec = layout.column(align=True)
                sec.label(icon="MOD_SOLIDIFY", text="Sector Properties")
                sec.prop(ob, "ceiling_height"); sec.prop(ob, "floor_height")
                mat = layout.column(align=True)
                mat.label(icon="MATERIAL", text="Sector Materials")
                mat.prop_search(ob, "ceiling_texture", bpy.data, "materials", icon="MATERIAL", text="Ceiling")
                mat.prop_search(ob, "wall_texture", bpy.data, "materials", icon="MATERIAL", text="Wall")
                mat.prop_search(ob, "floor_texture", bpy.data, "materials", icon="MATERIAL", text="Floor")

            if getattr(ob, "brush_type", 'NONE') == 'BRUSH':
                br = layout.column(align=True)
                br.label(icon="MATERIAL", text="Brush Material")
                br.prop_search(ob, "brush_material", bpy.data, "materials", icon="MATERIAL", text="Material")

class VertexColorPanel(bpy.types.Panel):
    bl_idname = "OBJECT_PT_vertex_color_panel"
    bl_label = "Color Attribute"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Level Buddy"
    def draw(self, context):
        layout = self.layout
        scn = bpy.context.scene
        row = layout.row(align=True)
        row.prop(scn, "color_picker", text="")
        row.operator("object.set_vertex_color", text="Set Color")

# =========================
# SNAP TO GRID (world-space) — Edit mode tools
# =========================

vertex_positions = {}

def _sgs_validate_context(context):
    if not context.active_object: return False, "No active object"
    if context.active_object.type != 'MESH': return False, "Active object is not a mesh"
    if context.mode != 'EDIT_MESH': return False, "Not in Edit Mode"
    return True, ""

def _snap_vec_world(wco, gx, gy, gz):
    if gx > 0: wco.x = round(wco.x / gx) * gx
    if gy > 0: wco.y = round(wco.y / gy) * gy
    if gz > 0: wco.z = round(wco.z / gz) * gz
    return wco

def _sgs_snap_to_grid(obj, selected_verts, gx, gy, gz):
    if not selected_verts: return 0
    mw = obj.matrix_world; imw = mw.inverted_safe()
    snapped = 0
    for v in selected_verts:
        old_local = v.co.copy()
        wco = mw @ old_local
        wco = _snap_vec_world(wco, gx, gy, gz)
        new_local = imw @ wco
        if (new_local - old_local).length > 1e-6:
            v.co = new_local; snapped += 1
    return snapped

def continuous_snap_handler(scene):
    global vertex_positions
    if bpy.context.mode != 'EDIT_MESH' or not scene.continuous_snap:
        return
    obj = bpy.context.active_object
    if not obj or obj.type != 'MESH': return
    mesh = obj.data
    bm = bmesh.from_edit_mesh(mesh)
    selected_verts = [v for v in bm.verts if v.select]
    if not selected_verts:
        vertex_positions.clear(); return
    moved = False
    for v in selected_verts:
        key = (obj.name, v.index)
        cur = v.co.copy()
        if key in vertex_positions and (cur - vertex_positions[key]).length > 0.0001:
            moved = True
        vertex_positions[key] = cur
    if moved:
        _sgs_snap_to_grid(obj, selected_verts, scene.grid_size_x, scene.grid_size_y, scene.grid_size_z)
        bmesh.update_edit_mesh(mesh)

class ERF_SnapToGridPanel(bpy.types.Panel):
    bl_label = "Snap to Grid"
    bl_idname = "VIEW3D_PT_erf_snap_to_grid"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Level Buddy'
    bl_context = 'mesh_edit'
    def draw(self, context):
        layout = self.layout; scene = context.scene
        box = layout.box(); box.label(text="Grid Settings:")
        box.prop(scene, "grid_size_x", text="Grid Size X")
        box.prop(scene, "grid_size_y", text="Grid Size Y")
        box.prop(scene, "grid_size_z", text="Grid Size Z")
        row = box.row(align=True); row.operator("mesh.reset_grid_sizes", text="Reset to Default")
        layout.separator(); layout.operator("mesh.snap_to_grid", text="Snap Selected to Grid")
        layout.separator(); box = layout.box(); box.label(text="Continuous Snapping:")
        row = box.row(align=True); row.operator("mesh.toggle_continuous_snap", text="Toggle Continuous Snap")
        icon = 'CHECKBOX_HLT' if scene.continuous_snap else 'CHECKBOX_DEHLT'
        status_text = "ON" if scene.continuous_snap else "OFF"
        row.label(text=f"Status: {status_text}", icon=icon)
        if scene.continuous_snap: box.label(text="⚠ World-space snapping active", icon='INFO')

class ERF_SnapToGridOperator(bpy.types.Operator):
    bl_idname = "mesh.snap_to_grid"
    bl_label = "Snap to Grid"
    bl_options = {'REGISTER', 'UNDO'}
    @classmethod
    def poll(cls, context): ok, _ = _sgs_validate_context(context); return ok
    def execute(self, context):
        try:
            ok, msg = _sgs_validate_context(context)
            if not ok: self.report({'ERROR'}, msg); return {'CANCELLED'}
            obj = context.active_object; bm = bmesh.from_edit_mesh(obj.data)
            sel = [v for v in bm.verts if v.select]
            if not sel:
                self.report({'INFO'}, "No vertices selected. Please select vertices in Edit Mode.")
                return {'CANCELLED'}
            snapped_count = _sgs_snap_to_grid(
                obj, sel, context.scene.grid_size_x, context.scene.grid_size_y, context.scene.grid_size_z
            )
            bmesh.update_edit_mesh(obj.data)
            self.report({'INFO'}, f"Snapped {snapped_count}/{len(sel)} vertices to world grid." if snapped_count>0 else "No vertices needed snapping (already on grid).")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Error during grid snapping: {str(e)}"); return {'CANCELLED'}

class ERF_ToggleContinuousSnapOperator(bpy.types.Operator):
    bl_idname = "mesh.toggle_continuous_snap"
    bl_label = "Toggle Continuous Snap"
    bl_options = {'REGISTER', 'UNDO'}
    @classmethod
    def poll(cls, context): ok, _ = _sgs_validate_context(context); return ok
    def execute(self, context):
        try:
            context.scene.continuous_snap = not context.scene.continuous_snap
            if context.scene.continuous_snap:
                if continuous_snap_handler not in bpy.app.handlers.depsgraph_update_post:
                    bpy.app.handlers.depsgraph_update_post.append(continuous_snap_handler)
                self.report({'INFO'}, "Continuous snapping ON (world-space).")
            else:
                if continuous_snap_handler in bpy.app.handlers.depsgraph_update_post:
                    bpy.app.handlers.depsgraph_update_post.remove(continuous_snap_handler)
                self.report({'INFO'}, "Continuous snapping OFF.")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Error toggling continuous snap: {str(e)}"); return {'CANCELLED'}

class ERF_ResetGridSizesOperator(bpy.types.Operator):
    bl_idname = "mesh.reset_grid_sizes"
    bl_label = "Reset Grid Sizes"
    bl_description = "Reset all grid sizes to default values"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        context.scene.grid_size_x = 1.0; context.scene.grid_size_y = 1.0; context.scene.grid_size_z = 1.0
        self.report({'INFO'}, "Grid sizes reset to default (1.0)"); return {'FINISHED'}

# =========================
# operators (rest)
# =========================

class LevelBuddyNewGeometry(bpy.types.Operator):
    bl_idname = "scene.level_buddy_new_geometry"
    bl_label = "Level New Geometry"
    brush_type: bpy.props.StringProperty(name="brush_type", default='NONE')
    @classmethod
    def poll(cls, context): return context.mode == 'OBJECT'
    def add_vertex_color(self, ob):
        ensure_color_layer(ob.data); fill_color_layer_object_mode(ob, (1.0, 1.0, 1.0, 1.0))
    def _set_default_visibility(self, ob):
        try: ob.hide_select = False
        except Exception: pass
        try: ob.hide_set(False)
        except Exception: pass
        try: ob.hide_render = True
        except Exception: pass
        for attr in ("visible_camera","visible_diffuse","visible_glossy","visible_transmission","visible_volume_scatter","visible_shadow"):
            if hasattr(ob, attr):
                try: setattr(ob, attr, False)
                except Exception: pass
    def execute(self, context):
        bpy.ops.object.select_all(action='DESELECT')
        if self.brush_type == 'SECTOR': bpy.ops.mesh.primitive_plane_add(size=2)
        else: bpy.ops.mesh.primitive_cube_add(size=2)
        ob = bpy.context.active_object
        ob.csg_operation = 'ADD'; ob.display_type = 'WIRE'
        ob.name = self.brush_type; ob.data.name = self.brush_type
        ob.brush_type = self.brush_type; ob.csg_order = 0; ob.brush_auto_texture = True
        bpy.context.view_layer.objects.active = ob
        self._set_default_visibility(ob)
        ob.ceiling_height = 4; ob.floor_height = 0
        ob.ceiling_texture_scale_offset = (1.0, 1.0, 0.0, 0.0)
        ob.wall_texture_scale_offset = (1.0, 1.0, 0.0, 0.0)
        ob.floor_texture_scale_offset = (1.0, 1.0, 0.0, 0.0)
        ob.ceiling_texture_rotation = 0; ob.wall_texture_rotation = 0; ob.floor_texture_rotation = 0
        ob.ceiling_texture = ""; ob.wall_texture = ""; ob.floor_texture = ""
        self.add_vertex_color(ob); update_brush(ob)
        return {"FINISHED"}

class LevelBuddyBuildMap(bpy.types.Operator):
    bl_idname = "scene.level_buddy_build_map"
    bl_label = "Build Map"
    bool_op: bpy.props.StringProperty(name="bool_op", default="UNION")
    def execute(self, context):
        scn = bpy.context.scene
        was_edit_mode = False
        old_active = bpy.context.active_object
        old_selected = bpy.context.selected_objects.copy()
        if bpy.context.mode == 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='OBJECT'); was_edit_mode = True

        brush_dictionary_list = {}; brush_orders_sorted_list = []
        level_map = create_new_boolean_object(scn, "LevelGeometry")
        level_map.data = bpy.data.meshes.new("LevelGeometryMesh")

        ensure_color_layer(level_map.data)
        mesh = level_map.data
        if hasattr(mesh, "use_auto_smooth"): mesh.use_auto_smooth = scn.map_use_auto_smooth
        if hasattr(mesh, "auto_smooth_angle"): mesh.auto_smooth_angle = math.radians(scn.map_auto_smooth_angle)

        level_map.hide_select = True; level_map.hide_set(False)

        for ob in bpy.context.scene.collection.all_objects:
            if not ob or ob == level_map: continue
            if getattr(ob, "brush_type", 'NONE') == 'NONE': continue
            update_brush(ob)
            if brush_dictionary_list.get(ob.csg_order, None) is None:
                brush_dictionary_list[ob.csg_order] = []
            if ob.csg_order not in brush_orders_sorted_list:
                brush_orders_sorted_list.append(ob.csg_order)
            brush_dictionary_list[ob.csg_order].append(ob)

        brush_orders_sorted_list.sort()
        bpy.context.view_layer.objects.active = level_map

        name_index = 0
        for order in brush_orders_sorted_list:
            for brush in brush_dictionary_list[order]:
                brush.name = brush.csg_operation + "[" + str(order) + "]" + str(name_index); name_index += 1
                bool_obj = build_bool_object(brush)
                if brush.brush_auto_texture: auto_texture(bool_obj, brush)
                ensure_color_layer(bool_obj.data)
                apply_csg(level_map, brush, bool_obj, reporter=self)

        # final clean-up on result mesh
        _cleanup_result_mesh(level_map.data, merge_dist=1e-5, angle_limit=0.0)

        # optional world-space snap of final geometry
        if scn.post_build_snap_enable and scn.post_build_snap_step > 0.0:
            snap_object_mesh_world(level_map, scn.post_build_snap_step)

        remove_material(level_map)
        update_location_precision(level_map)
        set_normals_inward(level_map)

        bpy.ops.object.select_all(action='DESELECT')
        if old_active:
            old_active.select_set(True); bpy.context.view_layer.objects.active = old_active
        if was_edit_mode: bpy.ops.object.mode_set(mode='EDIT')
        for obj in old_selected:
            if obj: obj.select_set(True)

        for o in list(bpy.data.objects):
            if o.users == 0: bpy.data.objects.remove(o)
        for m in list(bpy.data.meshes):
            if m.users == 0: bpy.data.meshes.remove(m)
        return {"FINISHED"}

class SetVertexColorOperator(bpy.types.Operator):
    bl_idname = "object.set_vertex_color"
    bl_label = "Set Vertex Color"
    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH': return {'CANCELLED'}
        color = bpy.context.scene.color_picker
        ensure_color_layer(obj.data); fill_color_layer_object_mode(obj, (color[0], color[1], color[2], 1.0))
        return {'FINISHED'}

# =========================
# register
# =========================

def _register_grid_props():
    bpy.types.Scene.grid_size_x = bpy.props.FloatProperty(
        name="Grid Size X", default=1.0, min=0.01, max=100.0, precision=3,
        description="Grid snapping size for the X-axis (world space)"
    )
    bpy.types.Scene.grid_size_y = bpy.props.FloatProperty(
        name="Grid Size Y", default=1.0, min=0.01, max=100.0, precision=3,
        description="Grid snapping size for the Y-axis (world space)"
    )
    bpy.types.Scene.grid_size_z = bpy.props.FloatProperty(
        name="Grid Size Z", default=1.0, min=0.01, max=100.0, precision=3,
        description="Grid snapping size for the Z-axis (world space)"
    )
    bpy.types.Scene.continuous_snap = bpy.props.BoolProperty(
        name="Continuous Snap", default=False,
        description="Enable continuous world-space snapping of selected vertices while editing"
    )

CLASSES = (
    LevelBuddyPanel,
    VertexColorPanel,
    LevelBuddyBuildMap,
    LevelBuddyNewGeometry,
    SetVertexColorOperator,

    # Snap to Grid (edit mode)
    ERF_SnapToGridPanel,
    ERF_SnapToGridOperator,
    ERF_ToggleContinuousSnapOperator,
    ERF_ResetGridSizesOperator,
)

def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    _register_grid_props()

def unregister():
    if continuous_snap_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(continuous_snap_handler)
    for cls in reversed(CLASSES):
        try: bpy.utils.unregister_class(cls)
        except Exception: pass
    for attr in ("grid_size_x", "grid_size_y", "grid_size_z", "continuous_snap"):
        try: delattr(bpy.types.Scene, attr)
        except Exception: pass

if __name__ == "__main__":
    register()
