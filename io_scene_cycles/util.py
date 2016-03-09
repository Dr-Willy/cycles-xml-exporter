
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


