"""
WebODM-lite: 2D-only processing profile.

Every task sent to a processing node goes through enforce_lite_options(),
which forces an orthophoto-only pipeline (fast-orthophoto) and strips any
option that would trigger 3D outputs (full 3D mesh, textured model, 3D tiles,
point cloud exports, DEMs).
"""

# Options forced on every task
FORCED_OPTIONS = {
    'fast-orthophoto': True,   # skip dense reconstruction (no dense point cloud)
    'skip-3dmodel': True,      # skip full 3D mesh / textured 3D model (keeps the 2.5D mesh used by the orthophoto)
    'skip-report': True,       # skip PDF report (renders point cloud / DEM previews)
    'use-3dmesh': False,
    'dsm': False,
    'dtm': False,
    '3d-tiles': False,
    'gltf': False,
    'pc-las': False,
    'pc-csv': False,
    'pc-ept': False,
    'pc-copc': False,
}

# Options removed from every task (only meaningful for 3D / DEM outputs).
# texturing-* and pc-filter/pc-sample are kept: they still affect the orthophoto.
STRIPPED_OPTIONS = (
    'mesh-octree-depth',
    'pc-quality',
    'pc-classify',
    'pc-rectify',
    'pc-geometric',
    'pc-skip-geometric',
    'dem-resolution',
    'dem-gapfill-steps',
    'dem-euclidean-map',
    'dem-decimation',
)


def enforce_lite_options(opts, available_options=None):
    """
    :param opts: dict of {optionName: value}
    :param available_options: list of option descriptors from the processing node
        (ProcessingNode.available_options). When provided, forced options that the
        node does not support are not sent (unknown options would make the node reject the task).
    :return: new dict with the lite profile applied
    """
    opts = {k: v for k, v in (opts or {}).items() if k not in STRIPPED_OPTIONS}

    supported = None
    if available_options:
        supported = set(o.get('name') for o in available_options if isinstance(o, dict))

    for name, value in FORCED_OPTIONS.items():
        if value is True and (supported is None or name in supported):
            opts[name] = value
        else:
            # Disabled flags are simply not sent (False is the node default)
            opts.pop(name, None)

    return opts
