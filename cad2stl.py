"""Color-preserving STEP to named STL patches, using OCCT directly."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile

VERSION = '0.3.0'
import cad_backend as backend
MISSING_COLOR = backend.MISSING_COLOR


class ConversionError(ValueError):
    pass


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def positive(value, name):
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ConversionError(f'{name} must be finite and positive')
    return value


def validate_map(value):
    if not isinstance(value, dict) or not value:
        raise ConversionError('color map must be a nonempty JSON object')
    result = {}
    names = set()
    for color, name in value.items():
        if not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            raise ConversionError('color keys must be #RRGGBB')
        color = color.upper()
        if color in result:
            raise ConversionError('duplicate normalized color')
        if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', name)
                or name.casefold() in {'con', 'prn', 'aux', 'nul', 'all_regions', 'report'}
                or re.fullmatch(r'(com|lpt)[1-9]', name, re.I)):
            raise ConversionError(f'invalid boundary name: {name!r}')
        # One color per named patch; assigning several colors to a patch is explicit out of scope.
        if name.casefold() in names:
            raise ConversionError('boundary names must be unique, ignoring case')
        result[color] = name
        names.add(name.casefold())
    return result


def color_key(color):
    rgb = tuple(float(x) for x in color[:3])
    if len(rgb) != 3 or any(not math.isfinite(x) or x < 0 or x > 1 for x in rgb):
        raise ConversionError('invalid face RGB values')
    return '#' + ''.join(f'{int(math.floor(x * 255 + .5)):02X}' for x in rgb)


def load_step(source):
    return backend.load_step(Path(source).resolve(), color_key, ConversionError)


inventory = backend.inventory
geometry_issues = backend.geometry_issues


def automatic_map(colors):
    return {color: 'color_' + color[1:] for color in sorted(colors) if color != MISSING_COLOR}


def inspect_step(source):
    with load_step(source) as items:
        faces = inventory(items)
        issues = geometry_issues(items)
    return dict(input_sha256=sha256(source), faces=faces,
                colors=dict(sorted(Counter(f['color'] for f in faces).items())),
                suggested_color_map=automatic_map({f['color'] for f in faces}),
                geometry_issues=issues,
                missing_color_sentinel=MISSING_COLOR,
                units='millimetres; STEP units normalized by OCCT importer')


def triangle_geometry(triangle):
    a, b, c = triangle
    ab = [b[i]-a[i] for i in range(3)]
    ac = [c[i]-a[i] for i in range(3)]
    cross = (ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2], ab[0]*ac[1]-ab[1]*ac[0])
    size = math.sqrt(sum(x*x for x in cross))
    if not math.isfinite(size) or size <= 0:
        raise ConversionError('Degenerate or nonfinite triangle encountered')
    return [x/size for x in cross], size/2


def write_solid(stream, name, triangles):
    stream.write(f'solid {name}\n')
    for triangle in triangles:
        normal, _ = triangle_geometry(triangle)
        stream.write('  facet normal ' + ' '.join(f'{x:.17g}' for x in normal) + '\n    outer loop\n')
        for vertex in triangle:
            stream.write('      vertex ' + ' '.join(f'{x:.17g}' for x in vertex) + '\n')
        stream.write('    endloop\n  endfacet\n')
    stream.write(f'endsolid {name}\n')


def convert(source, output, color_map, scale, linear_deflection=.05, angular_deflection=.2):
    scale = positive(scale, 'scale (mm to output units)')
    positive(linear_deflection, 'linear_deflection_mm')
    positive(angular_deflection, 'angular_deflection_rad')
    if angular_deflection > math.pi:
        raise ConversionError('angular_deflection_rad must be <= pi')
    if color_map is not None:
        color_map = validate_map(color_map)
    output = Path(output).resolve()
    if output.exists():
        raise ConversionError('Output already exists; choose a new directory')
    source = Path(source).resolve()
    groups = defaultdict(list)
    with load_step(source) as items:
        faces = inventory(items)
        used = {face['color'] for face in faces}
        if MISSING_COLOR in used:
            raise ConversionError('Missing face/body colors (UNCOLORED)')
        if color_map is None:
            color_map = validate_map(automatic_map(used))
        unknown = used - color_map.keys()
        if unknown:
            raise ConversionError('Unmapped colors: ' + ', '.join(sorted(unknown)))
        for part in items:
            for color, triangle in backend.tessellate(part, linear_deflection, angular_deflection, scale, ConversionError):
                if any(not math.isfinite(v) for point in triangle for v in point):
                    raise ConversionError('Nonfinite mesh coordinate')
                triangle_geometry(triangle)
                groups[color_map[color]].append(triangle)
        issues = geometry_issues(items)
        report = dict(version=VERSION, engine="OCCT via OCP", ocp_version=backend.ENGINE_VERSION,
                      input_name=source.name, input_sha256=sha256(source),
                      scale_from_mm=scale, linear_deflection_mm=linear_deflection,
                      angular_deflection_rad=angular_deflection, color_quantization='nearest 8-bit RGB',
                      color_map=color_map, unused_colors=sorted(color_map.keys()-used), faces=faces,
                      status='generated_requires_geometry_review' if issues else 'generated_requires_surface_validation',
                      geometry_issues=issues, openfoam_quality_verified=False,
                      warnings=['Individual boundary patches may be open.',
                                'No healing, internal contact-face removal or fluid-side normal inference.',
                                'Self intersections and OpenFOAM mesh quality require downstream validation.'],
                      patches={})
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.cad2stl-incomplete-', dir=output.parent))
    try:
        for name, triangles in sorted(groups.items()):
            path = stage / f'{name}.stl'
            with path.open('x', encoding='ascii', newline='\n') as stream:
                write_solid(stream, name, triangles)
            points = [p for t in triangles for p in t]
            report['patches'][name] = dict(file=path.name, triangles=len(triangles),
                mesh_area=sum(triangle_geometry(t)[1] for t in triangles),
                bbox=[[min(p[i] for p in points) for i in range(3)],
                      [max(p[i] for p in points) for i in range(3)]], sha256=sha256(path))
        with (stage/'all_regions.stl').open('x', encoding='ascii', newline='\n') as stream:
            for name, triangles in sorted(groups.items()):
                write_solid(stream, name, triangles)
        geometry = ['// Insert into snappyHexMeshDict. Do not also load all_regions.stl.', 'geometry', '{']
        refinement = ['// Insert inside castellatedMeshControls; choose levels for your case.', 'refinementSurfaces', '{']
        for name in sorted(groups):
            geometry += [f'    {name}.stl', '    {', '        type triSurfaceMesh;', f'        name {name};',
                         f'        regions {{ {name} {{ name {name}; }} }}', '    }']
            refinement += [f'    {name} {{ level (1 1); patchInfo {{ type patch; }} }}']
        (stage/'geometry.foam').write_text('\n'.join(geometry+['}', '']), encoding='ascii')
        (stage/'refinementSurfaces.foam').write_text('\n'.join(refinement+['}', '']), encoding='ascii')
        write_json(stage/'report.json', report)
        # os.rename is no-overwrite for existing directories on Windows; recheck for other OS.
        if output.exists():
            raise ConversionError('Output appeared during conversion; refusing overwrite')
        stage.rename(output)
    finally:
        if stage.exists() and stage.resolve().parent == output.parent and stage.name.startswith('.cad2stl-incomplete-'):
            shutil.rmtree(stage)
    return report


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] == 'serve':
        import web_app
        return web_app.main(argv[1:] if argv else [], open_browser=True) or 0
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('serve', help='Open the local Web application (default)')
    p = sub.add_parser('inspect', help='List imported face colors before mapping')
    p.add_argument('input', type=Path)
    p.add_argument('--report', required=True, type=Path)
    p = sub.add_parser('convert')
    p.add_argument('input', type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--map', type=Path, help='Optional #RRGGBB-to-boundary JSON; omitted: color_RRGGBB names')
    p.add_argument('--scale', required=True, type=float, help='Multiply normalized millimetres; 0.001 gives metres')
    p.add_argument('--linear-deflection', type=float, default=.05, help='millimetres')
    p.add_argument('--angular-deflection', type=float, default=.2, help='radians')
    args = parser.parse_args(argv)
    try:
        if args.action == 'inspect':
            if args.report.exists():
                raise ConversionError('Report already exists')
            write_json(args.report, inspect_step(args.input))
        else:
            mapping = json.loads(args.map.read_text(encoding='utf-8-sig')) if args.map else None
            report = convert(args.input, args.output, mapping, args.scale,
                             args.linear_deflection, args.angular_deflection)
            if report['geometry_issues']:
                print('CAD2STL WARNING: input OCCT checks found geometry issues. Review report.json; output is not validated for OpenFOAM.', file=sys.stderr)
        print('CAD2STL: generation completed; inspect report.json and validate surface quality before use')
        return 0
    except Exception as exc:
        print(f'CAD2STL ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    if sys.stdout: sys.stdout.reconfigure(encoding='utf-8')
    if sys.stderr: sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
