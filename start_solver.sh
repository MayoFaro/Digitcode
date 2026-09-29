#!/bin/bash
# Lance le serveur web du solveur Digitcode et ouvre le navigateur.
cd /home/cedric/StudioProjects/digitcode/Digitcode || exit 1

(sleep 1 && xdg-open "http://127.0.0.1:5000") &

python3 -m digitcode.web
