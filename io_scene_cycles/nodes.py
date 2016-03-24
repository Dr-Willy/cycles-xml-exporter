
import random
import xml.etree.ElementTree as etree

from . import util

#_options = export_cycles._options
_options = {'inline_textures' : True}

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
        color = util.space_separated_float3(
            node.outputs['Color']
                .default_value[:3])

        return { 'value': color }
    elif node.type == 'VALUE':
        return {
            'value': '%f' % node.outputs['Value'].default_value
        }

    return {}


def gen_shader_node_tree(nodes,links,connect_later):
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

# from the Node Wrangler, by Barte
def write_material(material, tag_name='shader'):
#    pass
#def gen_material(material, tag_name='shader'):
    did_copy = False
    if not material.use_nodes:
        did_copy = True
        material = material.copy()
        material.use_nodes = True

   
    node_tree = material.node_tree
    # nodes, links = get_nodes_links(context)
    nodes = list(node_tree.nodes)
    links = node_tree.links

    output_nodes = [ n for n in nodes if n.type in ('OUTPUT', 'OUTPUT_WORLD','OUTPUT_MATERIAL')] 

    if not len(output_nodes):
        return None

    for onode in output_nodes:
        nodes.remove(onode)

    # tag_name is usually 'shader' but could be 'background' for world shaders
    shader = etree.Element(tag_name, { 'name': material.name })
    connect_later = []

    for snode in gen_shader_node_tree(nodes,links,connect_later):
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


