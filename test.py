
# usage: blender -b my_file.blend -P test.py

import bpy

from io_scene_cycles.export_cycles import export_scene as export

scene = bpy.context.scene

export('test.xml', scene)

