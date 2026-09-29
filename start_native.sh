#!/bin/bash
# Lance l'application native (PySide6) du solveur Digitcode.
cd /home/cedric/StudioProjects/digitcode/Digitcode || exit 1
python3 -m digitcode.native
