#!/usr/bin/env python3
"""Read-only pre-installation checks for WD My Cloud EX2 Ultra.
No packages installed, no data modified, no credentials collected.
Python 3.9-compatible stdlib only.
"""
import argparse
import json
import os
import platform
import shutil
import sys
from pathlib import Path

def inspect(root='/', app_dir=None):
    root=Path(root)
    arch=platform.machine().lower()
    checks=[]
    def add(key,ok,detail,required=True):
        checks.append({'id':key,'ok':bool(ok),'required':required,'detail':str(detail)})
    add('python',sys.version_info >= (3,9),sys.version.split()[0])
    add('architecture',arch in ('armv7l','armv7','armhf'),arch)
    add('os5_marker',(root/'etc/version').exists() or (root/'etc/wdmycloud').exists(),
        'WD OS5 marker not reliably identified; confirm My Cloud OS 5 in Dashboard',False)
    media=root/'mnt/HD/HD_a2/Public'
    install_parent=root/'mnt/HD/HD_a2/Nas_Prog'
    data_parent=root/'mnt/HD/HD_a2'
    add('media',media.is_dir(),str(media))
    add('install_parent',install_parent.is_dir(),str(install_parent))
    add('data_parent',data_parent.is_dir(),str(data_parent))
    add('install_writable',os.access(str(install_parent),os.W_OK) if install_parent.is_dir() else False,str(install_parent))
    add('data_writable',os.access(str(data_parent),os.W_OK) if data_parent.is_dir() else False,str(data_parent))
    usage=shutil.disk_usage(str(data_parent)) if data_parent.is_dir() else None
    add('free_disk',usage is not None and usage.free >= 100*1024*1024,
        str(usage.free if usage else 'unknown')+' bytes free (minimum 100 MiB)')
    probe=shutil.which('ffprobe')
    if app_dir and (Path(app_dir)/'bin/ffprobe').is_file():
        probe=str(Path(app_dir)/'bin/ffprobe')
    add('ffprobe',bool(probe),probe or 'missing: video resolution cannot be established, all videos blocked',False)
    add('port_note',True,'Port 8097 availability and secure HTTPS reverse proxy must be checked on target',False)
    required=[x for x in checks if x['required']]
    return {'target':'WD My Cloud EX2 Ultra / OS5','ready_for_manual_install_review':all(x['ok'] for x in required),
            'installation_verified':False,'checks':checks}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',default='/')
    p.add_argument('--app-dir')
    p.add_argument('--json',action='store_true')
    args=p.parse_args()
    result=inspect(args.root,args.app_dir)
    if args.json:print(json.dumps(result,indent=2))
    else:
        for x in result['checks']:
            print(('[OK] ' if x['ok'] else '[WARN] ' if not x['required'] else '[FAIL] ')+x['id']+': '+x['detail'])
        print('Manual install review:', 'POSSIBLE' if result['ready_for_manual_install_review'] else 'BLOCKED')
        print('This is not a firmware installation test.')
    return 0 if result['ready_for_manual_install_review'] else 2

if __name__=='__main__':
    sys.exit(main())
