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

bl_info = {
    "name": "ERF Level Buddy",
    "author": "Matt Lucas, HickVieira, EvilReFlex",
    "version": (2, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Tools > Level Buddy",
    "description": "Workflow tools inspired by Doom and Unreal level mapping.",
    "warning": "",
    "wiki_url": "https://github.com/EvilReFlex/ERF_LevelBuddyBlender",
    "category": "Object",
}

IS_4X = bpy.app.version >= (4, 0, 0)
PREFERRED_COLOR_ATTR_NAME = "Attribute"

# ------------------------- helpers -------------------------

def translate(val, t):
    return val + t

def scale(val, s):
    return val * s

def rotate2D(uv, degrees):
    radians = math.radians(degrees)
    newUV = copy(uv)
    newUV.x = uv.x * math.cos(radians) - uv.y * math.sin(radians)
    newUV.y = uv.x * math.sin(radians) + uv.y * math.cos(radians)
    return newUV

def _get_attr_name():
    scn = bpy.context.scene
    name = getattr(scn, "color_attribute_name", "") or PREFERRED_COLOR_ATTR_NAME
    return name

def _activate_render_attr_40(mesh, layer):
    try:
        mesh.color_attributes.active_color = layer
    except Exception:
        pass
    try:
        mesh.color_attributes.render_color = layer
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
        layer = mesh.color_attributes.get(prefer_name)
        if layer is None:
            layer = mesh.color_attributes.get("Col") or mesh.color_attributes.get("Color")
        if layer is None:
            layer = mesh.color_attributes.new(
                name=prefer_name,
                domain='CORNER',
                type='BYTE_COLOR'  # entspricht Vertex Paint Default
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

# ---------------------- core functionality ----------------------

def auto_texture(bool_obj, source_obj):
    mesh = bool_obj.data
    objectLocation = source_obj.location
    objectScale = source_obj.scale

    bm = bmesh.new()
    bm.from_mesh(mesh)

    uv_layer = bm.loops.layers.uv.verify()
    for f in bm.faces:
        nX = abs(f.normal.x)
        nY = abs(f.normal.y)
        nZ = abs(f.normal.z)
        faceNormalLargest = nX
        faceDirection = "x"
        if faceNormalLargest < nY:
            faceNormalLargest = nY
            faceDirection = "y"
        if faceNormalLargest < nZ:
            faceNormalLargest = nZ
            faceDirection = "z"
        if faceDirection == "x" and f.normal.x < 0:
            faceDirection = "-x"
        if faceDirection == "y" and f.normal.y < 0:
            faceDirection = "-y"
        if faceDirection == "z" and f.normal.z < 0:
            faceDirection = "-z"
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
    ob.location.x = round(ob.location.x, bpy.context.scene.map_precision)
    ob.location.y = round(ob.location.y, bpy.context.scene.map_precision)
    ob.location.z = round(ob.location.z, bpy.context.scene.map_precision)
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
            try:
                mod.use_quality_normals = True
            except Exception:
                pass
            mod.thickness = ob.ceiling_height - ob.floor_height
            if mod.thickness != 0:
                mod.offset = 1 + ob.floor_height / (mod.thickness / 2)
            mod.material_offset = 1
            mod.material_offset_rim = 2
            break

def update_brush_sector_materials(ob):
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

def update_brush(obj):
    bpy.context.view_layer.objects.active = obj
    if obj:
        obj.display_type = 'WIRE'
        update_brush_sector_modifier(obj)
        if obj.brush_type == 'SECTOR':
            update_brush_sector_materials(obj)
        update_location_precision(obj)

def cleanup_vertex_precision(ob):
    for v in ob.data.vertices:
        v.co.x = round(v.co.x, bpy.context.scene.map_precision)
        v.co.y = round(v.co.y, bpy.context.scene.map_precision)
        v.co.z = round(v.co.z, bpy.context.scene.map_precision)

def apply_csg(target, source_obj, bool_obj, reporter=None):
    # Sicherstellen: Ziel/Bool haben Color-Attribute (für Propagation)
    if target.data:
        ensure_color_layer(target.data)
    if bool_obj.data:
        ensure_color_layer(bool_obj.data)

    bpy.ops.object.select_all(action='DESELECT')
    target.select_set(True)

    copy_materials(target, source_obj)

    mod = target.modifiers.new(name=source_obj.name, type='BOOLEAN')
    mod.object = bool_obj
    mod.operation = csg_operation_to_blender_boolean[source_obj.csg_operation]
    mod.solver = 'EXACT'
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

    if me is not None:
        ensure_color_layer(me)

    ob_bool = bpy.data.objects.new("_booley", me)
    copy_transforms(ob_bool, sourceObj)
    cleanup_vertex_precision(ob_bool)
    return ob_bool

def create_new_boolean_object(scn, name):
    old_map = None
    if bpy.data.meshes.get(name + "_MESH") is not None:
        old_map = bpy.data.meshes[name + "_MESH"]
        old_map.name = "map_old"
    me = bpy.data.meshes.new(name + "_MESH")
    if bpy.data.objects.get(name) is None:
        ob = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(ob)
    else:
        ob = bpy.data.objects[name]
        ob.data = me
    if old_map is not None:
        bpy.data.meshes.remove(old_map)
    ob.select_set(True)
    return ob

def copy_materials(target, source):
    if source.data is None:
        return
    if source.data.materials is None:
        return
    for sourceMaterial in source.data.materials:
        if sourceMaterial is not None:
            if sourceMaterial.name not in target.data.materials:
                target.data.materials.append(sourceMaterial)

def copy_transforms(a, b):
    a.location = b.location
    a.scale = b.scale
    a.rotation_euler = b.rotation_euler

def set_normals_inward(ob):
    """Orientiere Normalen konsistent nach innen."""
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
    if not name:
        return
    i = 0
    remove = False
    for m in obj.material_slots:
        if m.name == name:
            remove = True
        else:
            if not remove:
                i += 1
    if remove:
        obj.active_material_index = i
        bpy.ops.object.editmode_toggle()
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.object.material_slot_select()
        bpy.ops.mesh.delete(type='FACE')
        bpy.ops.object.editmode_toggle()
        bpy.ops.object.material_slot_remove()

# ---------------------- properties ----------------------

bpy.types.Scene.map_precision = bpy.props.IntProperty(
    name="Map Precision",
    default=3,
    min=0,
    max=6,
    description="Rounding level of vertex precision"
)
bpy.types.Scene.map_use_auto_smooth = bpy.props.BoolProperty(
    name="Map Auto Smooth",
    description="Use auto smooth",
    default=True,
)
bpy.types.Scene.map_auto_smooth_angle = bpy.props.FloatProperty(
    name="Angle",
    description="Auto smooth angle",
    default=30,
    min=0,
    max=180,
    step=1,
    precision=0,
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

# Brush props
bpy.types.Object.ceiling_texture_scale_offset = bpy.props.FloatVectorProperty(
    name="Ceiling Texture Scale Offset",
    default=(1, 1, 0, 0),
    min=0,
    step=10,
    precision=3,
    size=4
)
bpy.types.Object.wall_texture_scale_offset = bpy.props.FloatVectorProperty(
    name="Wall Texture Scale Offset",
    default=(1, 1, 0, 0),
    min=0,
    step=10,
    precision=3,
    size=4
)
bpy.types.Object.floor_texture_scale_offset = bpy.props.FloatVectorProperty(
    name="Floor Texture Scale Offset",
    default=(1, 1, 0, 0),
    min=0,
    step=10,
    precision=3,
    size=4
)
bpy.types.Object.ceiling_texture_rotation = bpy.props.FloatProperty(
    name="Ceiling Texture Rotation",
    default=0,
    min=0,
    step=10,
    precision=3,
)
bpy.types.Object.wall_texture_rotation = bpy.props.FloatProperty(
    name="Wall Texture Rotation",
    default=0,
    min=0,
    step=10,
    precision=3,
)
bpy.types.Object.floor_texture_rotation = bpy.props.FloatProperty(
    name="Floor Texture Rotation",
    default=0,
    min=0,
    step=10,
    precision=3,
)
bpy.types.Object.ceiling_height = bpy.props.FloatProperty(
    name="Ceiling Height",
    default=4,
    step=10,
    precision=3,
    update=_update_sector_solidify
)
bpy.types.Object.floor_height = bpy.props.FloatProperty(
    name="Floor Height",
    default=0,
    step=10,
    precision=3,
    update=_update_sector_solidify
)
bpy.types.Object.floor_texture = bpy.props.StringProperty(name="Floor Texture")
bpy.types.Object.wall_texture = bpy.props.StringProperty(name="Wall Texture")
bpy.types.Object.ceiling_texture = bpy.props.StringProperty(name="Ceiling Texture")
bpy.types.Object.brush_type = bpy.props.EnumProperty(
    items=[("BRUSH", "Brush", "is a brush"),
           ("SECTOR", "Sector", "is a sector"),
           ("NONE", "None", "none")],
    name="Brush Type",
    description="the brush type",
    default='NONE'
)
bpy.types.Object.csg_operation = bpy.props.EnumProperty(
    items=[("ADD", "Add", "add/union geometry to output"),
           ("SUBTRACT", "Subtract", "subtract/remove geometry from output")],
    name="CSG Operation",
    description="the CSG operation",
    default='ADD'
)
csg_operation_to_blender_boolean = {
    "ADD": "UNION",
    "SUBTRACT": "DIFFERENCE"
}
bpy.types.Object.csg_order = bpy.props.IntProperty(
    name="CSG Order",
    default=0,
    description="Controls the order of CSG operation of the object"
)
bpy.types.Object.brush_auto_texture = bpy.props.BoolProperty(
    name="Brush Auto Texture",
    default=True,
    description="Auto Texture on or off"
)

# ---------------------- UI helpers ----------------------

def draw_uv_box(parent, obj, prop_name, label, rot_prop_name, rot_label="Rotation"):
    box = parent.box()
    col = box.column(align=True)
    col.label(text=label)
    # Scale row
    row = col.row(align=True)
    row.label(text="Scale")
    sub = row.row(align=True)
    sub.prop(obj, prop_name, index=0, text="U")
    sub.prop(obj, prop_name, index=1, text="V")
    # Shift row
    row2 = col.row(align=True)
    row2.label(text="Shift")
    sub2 = row2.row(align=True)
    sub2.prop(obj, prop_name, index=2, text="U")
    sub2.prop(obj, prop_name, index=3, text="V")
    # Rotation row
    row3 = col.row(align=True)
    row3.label(text=rot_label)
    row3.prop(obj, rot_prop_name, text="°")

# ---------------------- UI ----------------------

class LevelBuddyPanel(bpy.types.Panel):
    bl_label = "Level Buddy"
    bl_space_type = "VIEW_3D"
    bl_region_type = 'UI'
    bl_category = 'Level Buddy'
    def draw(self, context):
        ob = context.active_object
        scn = bpy.context.scene
        layout = self.layout

        # Map Settings
        col = layout.column(align=True)
        col.label(icon="WORLD", text="Map Settings")
        col.prop(scn, "map_precision")

        row = col.row(align=True)
        row.prop(scn, "map_use_auto_smooth", text="Auto Smooth")
        row.prop(scn, "map_auto_smooth_angle", text="Angle")

        col.prop_search(scn, "remove_material", bpy.data, "materials")
        col.separator()
        col.prop(scn, "color_attribute_name")

        # Build
        col = layout.column(align=True)
        col.operator("scene.level_buddy_build_map", text="Build Map", icon="MOD_BUILD").bool_op = "UNION"

        # Tools: New Sector / New Brush side-by-side
        col = layout.column(align=True)
        col.label(icon="SNAP_PEEL_OBJECT", text="Tools")
        row = col.row(align=True)
        op1 = row.operator("scene.level_buddy_new_geometry", text="New Sector", icon="MESH_PLANE")
        op1.brush_type = 'SECTOR'
        op2 = row.operator("scene.level_buddy_new_geometry", text="New Brush", icon="CUBE")
        op2.brush_type = 'BRUSH'

        # Brush Properties
        if ob is not None and len(bpy.context.selected_objects) > 0:
            col = layout.column(align=True)
            col.label(icon="MOD_ARRAY", text="Brush Properties")
            # Read-only Typanzeige statt Auswahlbox
            typ = getattr(ob, "brush_type", "NONE")
            col.label(text=f"Type: {typ.title() if isinstance(typ, str) else str(typ)}")
            col.prop(ob, "csg_operation", text="CSG Op")
            col.prop(ob, "csg_order", text="CSG Order")
            col.prop(ob, "brush_auto_texture", text="Auto Texture")

            if ob.brush_auto_texture:
                draw_uv_box(col, ob, "ceiling_texture_scale_offset", "Ceiling UV", "ceiling_texture_rotation")
                draw_uv_box(col, ob, "wall_texture_scale_offset", "Wall UV", "wall_texture_rotation")
                draw_uv_box(col, ob, "floor_texture_scale_offset", "Floor UV", "floor_texture_rotation")

            if ob.brush_type == 'SECTOR' and ob.modifiers:
                col = layout.column(align=True)
                col.label(icon="MOD_ARRAY", text="Sector Properties")
                col.prop(ob, "ceiling_height")
                col.prop(ob, "floor_height")
                col = layout.column(align=True)
                col.prop_search(ob, "ceiling_texture", bpy.data, "materials", icon="MATERIAL", text="Ceiling")
                col.prop_search(ob, "wall_texture", bpy.data, "materials", icon="MATERIAL", text="Wall")
                col.prop_search(ob, "floor_texture", bpy.data, "materials", icon="MATERIAL", text="Floor")

class VertexColorPanel(bpy.types.Panel):
    bl_idname = "OBJECT_PT_vertex_color_panel"
    bl_label = "Color Attribute"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Level Buddy"
    def draw(self, context):
        layout = self.layout
        scn = bpy.context.scene

        # Active Color + Button in einer Zeile
        row = layout.row(align=True)
        row.prop(scn, "color_picker", text="")
        btn = row.operator("object.set_vertex_color", text="Set Color")
        btn.icon = 'COLOR' if hasattr(btn, "icon") else 0  # falls verfügbar

# ---------------------- operators ----------------------

class LevelBuddyNewGeometry(bpy.types.Operator):
    bl_idname = "scene.level_buddy_new_geometry"
    bl_label = "Level New Geometry"
    brush_type: bpy.props.StringProperty(name="brush_type", default='NONE')

    def add_vertex_color(self, ob):
        white = (1.0, 1.0, 1.0, 1.0)
        ensure_color_layer(ob.data)
        fill_color_layer_object_mode(ob, white)

    def _set_default_visibility(self, ob):
        """Nur Viewport sichtbar & selektierbar. Alles andere aus."""
        try:
            ob.hide_select = False
        except Exception:
            pass
        try:
            ob.hide_set(False)
        except Exception:
            pass
        try:
            ob.hide_render = True
        except Exception:
            pass
        for attr in ("visible_camera",
                     "visible_diffuse",
                     "visible_glossy",
                     "visible_transmission",
                     "visible_volume_scatter",
                     "visible_shadow"):
            if hasattr(ob, attr):
                try:
                    setattr(ob, attr, False)
                except Exception:
                    pass

    def execute(self, context):
        bpy.ops.object.select_all(action='DESELECT')
        if self.brush_type == 'SECTOR':
            bpy.ops.mesh.primitive_plane_add(size=2)
        else:
            bpy.ops.mesh.primitive_cube_add(size=2)

        ob = bpy.context.active_object
        ob.csg_operation = 'ADD'
        ob.display_type = 'WIRE'
        ob.name = self.brush_type
        ob.data.name = self.brush_type
        ob.brush_type = self.brush_type
        ob.csg_order = 0
        ob.brush_auto_texture = True
        bpy.context.view_layer.objects.active = ob

        # Sichtbarkeit Defaults
        self._set_default_visibility(ob)

        # Defaults
        ob.ceiling_height = 4
        ob.floor_height = 0
        ob.ceiling_texture_scale_offset = (1.0, 1.0, 0.0, 0.0)
        ob.wall_texture_scale_offset = (1.0, 1.0, 0.0, 0.0)
        ob.floor_texture_scale_offset = (1.0, 1.0, 0.0, 0.0)
        ob.ceiling_texture_rotation = 0
        ob.wall_texture_rotation = 0
        ob.floor_texture_rotation = 0
        ob.ceiling_texture = ""
        ob.wall_texture = ""
        ob.floor_texture = ""

        # Color-Layer sofort weiß
        self.add_vertex_color(ob)

        update_brush(ob)
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
            bpy.ops.object.mode_set(mode='OBJECT')
            was_edit_mode = True

        brush_dictionary_list = {}
        brush_orders_sorted_list = []

        level_map = create_new_boolean_object(scn, "LevelGeometry")
        level_map.data = bpy.data.meshes.new("LevelGeometryMesh")

        # Ziel-Mesh: aktives Color-Attribut
        ensure_color_layer(level_map.data)

        # Auto smooth (nur 3.x Felder)
        mesh = level_map.data
        if hasattr(mesh, "use_auto_smooth"):
            mesh.use_auto_smooth = scn.map_use_auto_smooth
        if hasattr(mesh, "auto_smooth_angle"):
            mesh.auto_smooth_angle = math.radians(scn.map_auto_smooth_angle)

        level_map.hide_select = True
        level_map.hide_set(False)

        visible_objects = bpy.context.scene.collection.all_objects
        for ob in visible_objects:
            if not ob:
                continue
            if ob != level_map and getattr(ob, "brush_type", 'NONE') != 'NONE':
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
            brush_list = brush_dictionary_list[order]
            for brush in brush_list:
                brush.name = brush.csg_operation + "[" + str(order) + "]" + str(name_index)
                name_index += 1

                bool_obj = build_bool_object(brush)
                if brush.brush_auto_texture:
                    auto_texture(bool_obj, brush)
                ensure_color_layer(bool_obj.data)

                apply_csg(level_map, brush, bool_obj, reporter=self)

        remove_material(level_map)
        update_location_precision(level_map)

        # Normalen nach innen
        set_normals_inward(level_map)

        # Kontext zurücksetzen
        bpy.ops.object.select_all(action='DESELECT')
        if old_active:
            old_active.select_set(True)
            bpy.context.view_layer.objects.active = old_active
        if was_edit_mode:
            bpy.ops.object.mode_set(mode='EDIT')
        for obj in old_selected:
            if obj:
                obj.select_set(True)

        # Müll entfernen
        for o in list(bpy.data.objects):
            if o.users == 0:
                bpy.data.objects.remove(o)
        for m in list(bpy.data.meshes):
            if m.users == 0:
                bpy.data.meshes.remove(m)

        return {"FINISHED"}

class SetVertexColorOperator(bpy.types.Operator):
    bl_idname = "object.set_vertex_color"
    bl_label = "Set Vertex Color"

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            return {'CANCELLED'}
        color = bpy.context.scene.color_picker
        rgba = (color[0], color[1], color[2], 1.0)
        ensure_color_layer(obj.data)
        fill_color_layer_object_mode(obj, rgba)
        return {'FINISHED'}

# UI Color Picker
bpy.types.Scene.color_picker = bpy.props.FloatVectorProperty(
    name="Active",
    subtype='COLOR',
    default=(1.0, 1.0, 1.0),
    min=0.0,
    max=1.0
)

# ---------------------- register ----------------------

CLASSES = (
    LevelBuddyPanel,
    VertexColorPanel,
    LevelBuddyBuildMap,
    LevelBuddyNewGeometry,
    SetVertexColorOperator,
)

def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

if __name__ == "__main__":
    register()
