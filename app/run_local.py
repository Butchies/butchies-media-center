#!/usr/bin/env python3
"""Local-only smoke launcher. Not a WD dashboard installer."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description="Run Butchies Media Center on this computer only")
    parser.add_argument("--data",required=True,help="Directory for SQLite databases")
    parser.add_argument("--media",required=True,help="Directory containing test media")
    parser.add_argument("--port",type=int,default=8097)
    args=parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")
    data=Path(args.data).expanduser().resolve()
    media=Path(args.media).expanduser().resolve()
    if not media.is_dir():
        parser.error("media directory must exist")
    server=Path(__file__).with_name("server.py")
    if not server.is_file():
        parser.error("server.py fehlt im Repository. Dieses Repository ist noch kein lauffaehiges Gesamtpaket.")
    data.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy()
    env.update(BMC_BIND="127.0.0.1",BMC_DATA=str(data),BMC_MEDIA=str(media),BMC_PORT=str(args.port))
    print("Local-only server: http://127.0.0.1:%d/" % args.port,flush=True)
    return subprocess.call([sys.executable,str(server)],env=env)

if __name__=="__main__":
    sys.exit(main())
