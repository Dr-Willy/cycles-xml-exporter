
import math
import os
import mathutils
import bpy.types
import xml.etree.ElementTree as etree
import xml.dom.minidom as dom

from . import nodes,util

write_material = nodes.write_material

_options = {
        'inline_textures' : True,
        'preview'    : True,
        'format_xml' : True,
        'tabsize'    : 2,
        'tabwith'    : ' ',
        'endline'    : '\n'
        }


def _format(node):
    global _options
    prefix = _options['tabwith']*_options['tabsize']

    #DONT ! it does copy entire node then yield
    #yield from [prefix+line for line in node]

    for line in node:
        yield prefix+line


def _noformat(node, *argv):
    yield from node


format = _format
NL = _options['endline']

def xml_include(node, filepath):
    include = util.writer(filepath)
    for data in node:
        writer.send(data)
    writer.close()
    yield '<include src="'+filepath+'" />'+NL


#def smart_export(file_path, scene):
#    dirname =os.path.dirname(file_path)
#    with open(file_path, "w") as fp:
#        pass
        

def export_scene(filepath, scene):
    f = util.writer(filepath)
    nodes = gen_scene_nodes(scene)
    xml = gen_cycles(nodes)
    for data in xml:
        f.send(data)

    f.close()


def gen_cycles(node):
    yield '<cycles>'+NL
    yield from format(node)
    yield '</cycles>'+NL


def gen_scene_nodes(scene):
    yield write_film(scene)+NL
    
    yield from gen_camera(scene.camera)
    background = write_material(scene.world, 'background')
    if background:
        yield etree.tostring( background ).decode()

    for obj in scene.objects:
        if( obj.type not in ['MESH', 'CURVE', 'SURFACE', 'FONT', 'LAMP'] or
            not any([a and b for a,b in zip(scene.layers, obj.layers)]) or
            obj.hide_render ):
               continue

        if obj.dupli_type == 'NONE':
            print(obj.name)
            yield from gen_object(obj,scene)
        elif obj.dupli_type == "GROUP":
            for grp_obj in obj.dupli_group.objects:
                yield from gen_object(grp_obj, scene, obj.matrix_world)
        else:
            print("Duplication not supported:",obj.dupli_type,"Object", obj.name,"ignore")
            continue


def gen_camera(cam):
    matrix = cam.matrix_world * mathutils.Matrix.Scale(-1,4,(0,0,1))
    
    yield from gen_transform_matrix(matrix.transposed(), _options['format_xml'])
    yield write_camera(cam.data)+NL
    yield '</transform>'+NL

    
def gen_object(obj, scene, matrix_world_extra=None):
    written_materials = set()
    has_material = False

    materials = getattr(obj.data, 'materials', []) or getattr(obj, 'materials', [])
    for material in materials:
        if material == None : continue
        has_material= True
        if hash(material) not in written_materials:
            material_node = write_material(material)
            if material_node is not None:
                written_materials.add(hash(material))
                yield etree.tostring(material_node).decode()

    matrix = obj.matrix_world
    if matrix_world_extra :
        matrix = matrix_world_extra * obj.matrix_world
    
    yield from gen_transform_matrix(matrix.transposed(), _options['format_xml'])

    if has_material : yield '<state shader="'+materials[0].name+'" >'+NL

    if   obj.type in ('MESH','CURVE','FONT','SURFACE'):
        yield from gen_mesh(obj.to_mesh(scene, True, 'PREVIEW'))
    else : # obj.type == 'LAMP':
        yield write_light(obj)+NL

    if has_material : yield '</state>'+NL

    yield '</transform>'+NL


def write_camera(camera):

    if camera.type == 'ORTHO':
        camera_type = 'orthogonal'
    elif camera.type == 'PERSP':
        camera_type = 'perspective'
    else:
        raise Exception('Camera type %r unknown!' % camera.type)

    return '<camera type="'+camera_type+'" nearclip="'+str(camera.clip_start)+'" farclip="'+str(camera.clip_end)+'" focaldistance="'+str(camera.dof_distance)+'" sensorwidth="'+str(camera.sensor_width)+'" sensorheight="'+str(camera.sensor_height)+'" />'
#
#        # fabio: untested values. assuming to be the same as found here:
#        # http://www.blender.org/documentation/blender_python_api_2_57_release/bpy.types.Camera.html#bpy.types.Camera.clip_start
#        'nearclip': str(camera.clip_start),
#        'farclip': str(camera.clip_end),
#        'focaldistance': str(camera.dof_distance),
#        'fov': str(math.degrees(camera.angle)),
#        'sensorwidth': str(camera.sensor_width),
#        'sensorheight': str(camera.sensor_height),
#    })


def write_film(scene):
    render = scene.render
    scale = scene.render.resolution_percentage / 100.0
    size_x = int(scene.render.resolution_x * scale)
    size_y = int(scene.render.resolution_y * scale)

    return '<film width="'+str(size_x)+'" height="'+str(size_y)+'" />'


def write_light(l):
    # TODO export light's shader here? Where?
    return '<light P="'+' '.join(list(map(str,l.location)))+'" />'
#    return etree.Element('light', {
#        'P': '%f %f %f' % (
#            object.location[0],
#            object.location[1],
#            object.location[2])
#    })


def gen_mesh(mesh):
    col_align = _options['format_xml'] 
    head = '<mesh P'
    sp  = 6 if col_align else 1
    
    funcformat = lambda P: ' '.join( ' '.join((str(v.co.x),str(v.co.y),str(v.co.z))) for v in P )
    yield from gen_list(mesh.vertices, funcformat, head, col_align, 3)

    head = ' '*sp + 'nverts'
    funcformat = lambda faces: ' '.join( str(len(f.vertices)) for f in faces)
    yield from gen_list(mesh.tessfaces, funcformat, head, col_align, 50)

    head = ' '*sp+'verts'
    funcformat = lambda faces: ' '.join( ' '.join( str(i) for i in f.vertices ) for f in faces) 
    yield from gen_list(mesh.tessfaces, funcformat, head, col_align, 5)
    
    uvmap = [m for m in mesh.tessface_uv_textures if m.active_render]
    if len(uvmap):
        uvmap = uvmap[0].data #XXX: what if multiple render active  uvmaps ?
        head = ' '*sp+'uv'
        f = None #... 
        funcformat = lambda uvmap: ' '.join( ' '.join(str(c[0])+' '+str(c[1]) for c in f.uv) for f in uvmap )
        yield from gen_list(uvmap, funcformat, head, col_align, 1)

    yield '/>'+NL


def gen_list(lst, func, header, col_align=True, width=50):
    padding = (' '*(len(header)+2)) if col_align else ''
    bs=width
    size = len(lst)
    if size > bs:
        yield header + '="' + func(lst[:bs]) + NL
        i=bs
        while i+bs < size :
            yield padding + func(lst[i:i+bs]) + NL
            i += bs

        yield padding + func(lst[i:]) + '"' + NL
    elif size == 0:
        yield header + '=""' + NL
    else:
        yield header + '="' + func(lst) + '"' + NL


def gen_transform_matrix(mat,col_align=True):
    l = lambda mat: util.write_vector(mat[0])
    yield from gen_list(mat, l, '<transform matrix', col_align, 1)
    yield '>' + NL

