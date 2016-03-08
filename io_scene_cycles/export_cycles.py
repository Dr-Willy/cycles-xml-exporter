
import random
import math
import os
import mathutils
import bpy.types
import xml.etree.ElementTree as etree
import xml.dom.minidom as dom

_options = {
        'inline_textures' : True,
        'preview'    : True,
        'format_xml' : True,
        'tabsize'    : 2,
        'tabwith'    : ' ',
        'endline'    : '\n'
        }

def coroutine(func):
    def starter(*argv, **kwarg):
        gen = func(*argv, **kwarg)
        next(gen)
        return gen
    return starter
    
@coroutine
def writer(filepath):
    with open(filepath, 'w') as fp:
        while True:
            data = yield
            if not data : break
            fp.write(data)


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
    include = writger(filepath)
    for data in node:
        writer.send(data)
    writer.close()
    yield '<include src="'+filepath+'" />'+NL


#def smart_export(file_path, scene):
#    dirname =os.path.dirname(file_path)
#    with open(file_path, "w") as fp:
#        pass
        

def export_scene(filepath, scene):
    f = writer(filepath)
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
    background = etree.tostring(write_material(scene.world, 'background')).decode()
    if background: yield background

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


def wrap_in_transforms(xml_element, object):
    matrix = object.matrix_world

    if (object.type == 'CAMERA'):
        #Cameras looks at -Z
        scale = mathutils.Matrix.Scale(-1,4,(0,0,1))
        matrix = matrix.copy() * scale

    wrapper = etree.Element('transform', { 'matrix': space_separated_matrix(matrix.transposed()) })
    wrapper.append(xml_element)

    return wrapper


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


def write_object(object, scene):
    if object.type == 'MESH':
        node = write_mesh(object.to_mesh)
    elif object.type == 'LAMP':
        node = write_light(object)
    elif object.type == 'CAMERA':
        node = write_camera(object, scene)
    else:
        raise NotImplementedError('Object type: %r' % object.type)

    node = wrap_in_state(node, object)
    node = wrap_in_transforms(node, object)
    return node



# from the Node Wrangler, by Barte
def write_material(material, tag_name='shader'):
    did_copy = False
    if not material.use_nodes:
        did_copy = True
        material = material.copy()
        material.use_nodes = True

    def xlateSocket(typename, socketname):
        for i in xlate:
            if i[0]==typename:
                for j in i[2]:
                    if j[0]==socketname:
                        return j[1]
        return socketname
    
    def xlateType(typename ):
        for i in xlate:
            if i[0]==typename:
                return i[1]
        return typename.lower()
    
    def isConnected(socket, links):
        for link in links:
            if link.from_socket == socket or link.to_socket == socket:
                return True
        return False

    def is_output(node):
        return node.type in ('OUTPUT', 'OUTPUT_MATERIAL', 'OUTPUT_WORLD')

    def socketIndex(node, socket):
        socketindex=0
        countname=0
        for i in node.inputs:
            if i.name == socket.name:
             countname += 1
             if i==socket:
                socketindex=countname
        if socketindex>0:
            if countname>1:
                return str(socketindex)
            else:
                return ''
        countname=0
        for i in node.outputs:
            if i.name == socket.name:
                countname += 1
                if i==socket:
                    socketindex=countname
        if socketindex>0:
            if countname>1:
                return str(socketindex)
        return ''
    #           blender        <--->     cycles
    xlate = ( ("RGB",                   "color",()),
              ("BSDF_DIFFUSE",          "diffuse_bsdf",()),
              ("BSDF_TRANSPARENT",      "transparent_bsdf",()),
              ("BSDF_GLOSSY",           "glossy_bsdf",()),
              ("BUMP",                  "bump",()),
              ("FRESNEL",               "fresnel",()),
              ("MATH",                  "math",()),
              ("MIX_RGB",               "mix",()),
              ("MIX_SHADER",            "mix_closure",(("Shader","closure"),)),
              ("OUTPUT_MATERIAL",       "",()),
              ("SUBSURFACE_SCATTERING", "subsurface_scattering",()),
              ("TEX_IMAGE",             "image_texture",()),
              ("TEX_MAGIC",             "magic_texture",()),
              ("TEX_NOISE",             "noise_texture",()),
              ("TEX_COORD",             "texture_coordinate",()),
              ("TEX_CHECKER",           "checker_texture",()),
              ("NEW_GEOMETRY",          "geometry",()),
            )
    
    node_tree = material.node_tree
    # nodes, links = get_nodes_links(context)
    nodes, links = node_tree.nodes, node_tree.links

    output_nodes = list(filter(is_output, nodes))

    if not output_nodes:
        return None

    nodes = list(nodes)  # We don't want to remove the node from the actual scene.
    nodes.remove(output_nodes[0])

    shader_name = material.name

    # tag_name is usually 'shader' but could be 'background' for world shaders
    shader = etree.Element(tag_name, { 'name': shader_name })
    
    def socket_name(socket, node):
        # TODO don't do this. If it has a space, don't trust there's
        # no other with the same name but with underscores instead of spaces.
        return xlateSocket(node.type, socket.name.replace(' ', '')) + socketIndex(node, socket)
    
    def shader_node_name(node):
        if is_output(node):
            return 'output'

        return node.name.replace(' ', '_')

    def special_node_attrs(node):
        def image_src(image):
            path = node.image.filepath_raw
            if path.startswith('//'):
                path = path[2:]

            if _options['inline_textures']:
                return { 'src': path }
            else:
                import base64
                w, h = image.size
                image = image.copy()
                newimage = bpy.data.images.new('/tmp/cycles_export', width=w, height=h)
                newimage.file_format = 'PNG'
                newimage.pixels = [pix for pix in image.pixels]
                newimage.filepath_raw = '/tmp/cycles_export'
                newimage.save()
                with open('/tmp/cycles_export', 'rb') as fp:
                    return {
                        'src': path,
                        'inline': base64.b64encode(fp.read()).decode('ascii')
                    }
            
        if node.type == 'TEX_IMAGE' and node.image is not None:
            return image_src(node.image)
        elif node.type == 'RGB':
            color = space_separated_float3(
                node.outputs['Color']
                    .default_value[:3])

            return { 'value': color }
        elif node.type == 'VALUE':
            return {
                'value': '%f' % node.outputs['Value'].default_value
            }

        return {}

    connect_later = []

    def gen_shader_node_tree(nodes):
        for node in nodes:
            node_attrs = { 'name': shader_node_name(node) }
            node_name = xlateType(node.type)

            for input in node.inputs:
                if isConnected(input,links):
                    continue
                if not hasattr(input,'default_value'):
                    continue

                el = None
                sock = None
                if input.type == 'RGBA':
                    el = etree.Element('color', {
                        'value': '%f %f %f' % (
                            input.default_value[0],
                            input.default_value[1],
                            input.default_value[2],
                        )
                    })
                    sock = 'Color'
                elif input.type == 'VALUE':
                    el = etree.Element('value', { 'value': '%f' % input.default_value })
                    sock = 'Value'
                elif input.type == 'VECTOR':
                    pass  # TODO no mapping for this?
                else:
                    print('TODO: unsupported default_value for socket of type: %s', input.type);
                    print('(node %s, socket %s)' % (node.name, input.name))
                    continue

                if el is not None:
                    el.attrib['name'] = input.name + ''.join(
                        random.choice('abcdef')
                        for x in range(5))

                    connect_later.append((
                        el.attrib['name'],
                        sock,
                        node,
                        input
                    ))
                    yield el

            node_attrs.update(special_node_attrs(node))
            yield etree.Element(node_name, node_attrs)

    for snode in gen_shader_node_tree(nodes):
        if snode is not None:
            shader.append(snode)

    for link in links:
        from_node = shader_node_name(link.from_node)
        to_node = shader_node_name(link.to_node)

        from_socket = socket_name(link.from_socket, node=link.from_node)
        to_socket = socket_name(link.to_socket, node=link.to_node)

        shader.append(etree.Element('connect', {
            'from': '%s %s' % (from_node, from_socket.replace(' ', '_')),
            'to': '%s %s' % (to_node, to_socket.replace(' ', '_')),

            # uncomment to be compatible with the new proposed syntax for defining nodes
            # 'from_node': from_node,
            # 'to_node': to_node,
            # 'from_socket': from_socket,
            # 'to_socket': to_socket
        }))

    for fn, fs, tn, ts in connect_later:
        from_node = fn
        to_node = shader_node_name(tn)

        from_socket = fs
        to_socket = socket_name(ts, node=tn)

        shader.append(etree.Element('connect', {
            'from': '%s %s' % (from_node, from_socket.replace(' ', '_')),
            'to': '%s %s' % (to_node, to_socket.replace(' ', '_')),

            # uncomment to be compatible with the new proposed syntax for defining nodes
            # 'from_node': from_node,
            # 'to_node': to_node,
            # 'from_socket': from_socket,
            # 'to_socket': to_socket
        }))

    if did_copy:
        # TODO delete the material we created as a hack to support materials with use_nodes == False
        pass
    return shader


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


def write_mesh(mesh):
    # generate mesh node
    nverts = ""
    verts = ""

    P = ' '.join(space_separated_float3(v.co) for v in mesh.vertices)

    for i, f in enumerate(mesh.tessfaces):
        nverts += str(len(f.vertices)) + " "

        for v in f.vertices:
            verts += str(v) + " "

        verts += " "

    return etree.Element('mesh', attrib={'nverts': nverts, 'verts': verts, 'P': P})

def wrap_in_transforms(xml_element, object):
    matrix = object.matrix_world

    if (object.type == 'CAMERA'):
        #Cameras looks at -Z
        scale = mathutils.Matrix.Scale(-1,4,(0,0,1))
        matrix = matrix.copy() * scale

    wrapper = etree.Element('transform', { 'matrix': space_separated_matrix(matrix.transposed()) })
    wrapper.append(xml_element)

    return wrapper

def wrap_in_state(xml_element, object):
    # UNSUPPORTED: Meshes with multiple materials

    try:
        material = getattr(object.data, 'materials', [])[0]
    except LookupError:
        return xml_element

    state = etree.Element('state', {
        'shader': material.name
    })

    state.append(xml_element)

    return state

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
    l = lambda mat: write_vector(mat[0])
    yield from gen_list(mat, l, '<transform matrix', col_align, 1)
    yield '>' + NL


def write_vector(v):
    return ' '.join( str(c) for c in v )

def space_separated_float3(coords):
    float3 = list(map(str, coords))
    assert len(float3) == 3, 'tried to serialize %r into a float3' % float3
    return ' '.join(float3)

def space_separated_float4(coords):
    float4 = list(map(str, coords))
    assert len(float4) == 4, 'tried to serialize %r into a float4' % float4
    return ' '.join(float4)

def space_separated_matrix(matrix):
    return ' '.join(space_separated_float4(row) + ' ' for row in matrix)

def write(node, fp):
    # strip(node)
    s = etree.tostring(node, encoding='unicode')
    fp.write(s)
    fp.write('\n')

