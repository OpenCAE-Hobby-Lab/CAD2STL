# Third-party components

CAD2STL uses Open CASCADE Technology directly through CadQuery OCP.
FreeCAD is not used or included.

| Component | Version | Upstream / license |
| --- | --- | --- |
| cadquery-ocp-novtk / cadquery-ocp-proxy | 8.0.1.1.0 | https://github.com/CadQuery/OCP and https://github.com/CadQuery/ocp-build-system — Apache-2.0 |
| Open CASCADE Technology | 8.0.1 | https://github.com/Open-Cascade-SAS/OCCT — LGPL-2.1 with OCCT exception |
| Python | 3.12 | https://www.python.org/ — PSF license, including its third-party notices |
| PyInstaller bootloader | 6.22.3 | https://github.com/pyinstaller/pyinstaller — GPL with bootloader exception |

The portable build contains dynamically linked native libraries from the upstream
OCP wheel, including image/font support libraries and Microsoft runtime components.
The `licenses` folder in the portable package records their license texts and sources.
Keep that folder and this notice with the program when copying the portable folder.
CAD2STL uses the upstream OCP wheel without modification. Its native libraries are kept as
separate files in `_internal` and may be replaced with compatible builds.

Source and build instructions for these components are available from the upstream
projects above. CAD2STL source and build configuration are available at
https://github.com/OpenCAE-Hobby-Lab/CAD2STL.
