"""OCCT XDE STEP reader and double-precision face tessellator (no FreeCAD)."""
from contextlib import contextmanager
from dataclasses import dataclass

import OCP
from OCP.BOPAlgo import BOPAlgo_ArgumentAnalyzer
from OCP.BRep import BRep_Tool
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.Quantity import Quantity_TOC_sRGB
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Iterator
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.XCAFPrs import XCAFPrs
from OCP.collections import (
    Sequence_TDF_Label,
    IndexedDataMap_TopoDS_Shape_XCAFPrs_Style_TopTools_ShapeMapHasher,
)

ENGINE_VERSION = OCP.__version__
MISSING_COLOR = 'UNCOLORED'


@dataclass
class Part:
    name: str
    shape: object
    faces: list
    colors: list


def collect_faces(shape, styles, inherited=None, visible=True):
    """Walk located shapes so body colors propagate and face colors override."""
    if styles.Contains(shape):
        style = styles.FindFromKey(shape)
        visible = visible and style.IsVisible()
        if style.IsSetColorSurf():
            inherited = style.GetColorSurf().Values(Quantity_TOC_sRGB)
    if not visible:
        return
    if shape.ShapeType() == TopAbs_FACE:
        yield TopoDS.Face(shape), inherited
        return
    children = TopoDS_Iterator(shape, True, True)
    while children.More():
        yield from collect_faces(children.Value(), styles, inherited, visible)
        children.Next()


@contextmanager
def load_step(source, color_key, error):
    if source.suffix.lower() not in {'.step', '.stp'}:
        raise error('Supported input: .step/.stp. Parasolid direct import is not implemented.')
    if not source.is_file():
        raise error(f'Input file not found: {source}')
    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    if reader.ReadFile(str(source)) != IFSelect_RetDone:
        raise error('STEP read failed')
    # OCCT interprets this value in millimetres. Set after ReadFile, before Transfer.
    reader.ChangeReader().SetSystemLengthUnit(1.0)
    document = TDocStd_Document(TCollection_ExtendedString('BinXCAF'))
    if not reader.Transfer(document):
        raise error('STEP transfer failed')
    tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    roots = Sequence_TDF_Label()
    tool.GetFreeShapes(roots)
    parts = []
    for index in range(1, roots.Length() + 1):
        label = roots.Value(index)
        shape = tool.GetShape_s(label)
        styles = IndexedDataMap_TopoDS_Shape_XCAFPrs_Style_TopTools_ShapeMapHasher()
        XCAFPrs.CollectStyleSettings_s(label, TopLoc_Location(), styles)
        entries = list(collect_faces(shape, styles))
        if not entries:
            raise error('STEP contains no visible supported faces (wire-only/hidden geometry is unsupported)')
        faces, colors = zip(*entries)
        parts.append(Part(f'root_{index}', shape, list(faces),
                          [color_key(c) if c is not None else MISSING_COLOR for c in colors]))
    if not parts:
        raise error('STEP contains no supported faces')
    try:
        yield parts
    finally:
        # No XCAF application session, GUI, preferences or external CAD process is used.
        parts.clear()


def inventory(parts):
    records = []
    for part in parts:
        for index, (face, color) in enumerate(zip(part.faces, part.colors), 1):
            props = GProp_GProps()
            BRepGProp.SurfaceProperties_s(face, props)
            center = props.CentreOfMass()
            records.append(dict(object=part.name, label=part.name, face=index, color=color,
                                area_mm2=props.Mass(), center_mm=[center.X(), center.Y(), center.Z()]))
    return records


def geometry_issues(parts):
    issues = []
    for part in parts:
        if not BRepCheck_Analyzer(part.shape).IsValid():
            issues.append(dict(object=part.name, check='BRepCheck', detail='Invalid BRep'))
        analyzer = BOPAlgo_ArgumentAnalyzer()
        analyzer.SetShape1(part.shape)
        analyzer.ContinuityMode = True
        analyzer.CurveOnSurfaceMode = True
        analyzer.SelfInterMode = True
        analyzer.Perform()
        if analyzer.HasFaulty():
            statuses = sorted({str(result.GetCheckStatus()) for result in analyzer.GetCheckResult()})
            issues.append(dict(object=part.name, check='OCCT BOPAlgo', detail=', '.join(statuses)))
    return issues


def tessellate(part, linear, angular, scale, error):
    mesher = BRepMesh_IncrementalMesh(part.shape, linear, False, angular, False)
    if not mesher.IsDone():
        raise error('OCCT tessellation failed')
    for index, (face, color) in enumerate(zip(part.faces, part.colors), 1):
        location = TopLoc_Location()
        mesh = BRep_Tool.Triangulation_s(face, location)
        if mesh is None or mesh.NbTriangles() == 0:
            raise error(f'Empty triangulation: {part.name} face {index}')
        transform = location.Transformation()
        reverse = face.Orientation() == TopAbs_REVERSED
        for j in range(1, mesh.NbTriangles() + 1):
            nodes = list(mesh.Triangle(j).Get())
            if reverse:
                nodes[1], nodes[2] = nodes[2], nodes[1]
            points = [mesh.Node(n).Transformed(transform) for n in nodes]
            yield color, [tuple(v * scale for v in (p.X(), p.Y(), p.Z())) for p in points]
