#!/usr/bin/env python3
"""IW4x-32 v2.0 compatibility - NOT part of the zip. From v2.1 IW4x-32 is IW4x-32.sh + files/. A v2.0 install that
auto-updated still starts this file (play-linux.sh): it hands over to files/iw4x32.py, which moves backup/ into
files/, removes the old scripts and makes the new menu entries. Exit 20 tells the old play-linux.sh that the game was
started already (it stops on 20)."""
import os, subprocess, sys

here = os.path.dirname(os.path.abspath(__file__))
subprocess.call([sys.executable, os.path.join(here, "files", "iw4x32.py"), "--migrate"] + sys.argv[1:])
sys.exit(20)
