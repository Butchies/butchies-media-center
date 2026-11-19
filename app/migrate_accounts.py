#!/usr/bin/env python3
"""Offline, non-destructive SQLite migration. Does not stop running services."""
import argparse, os, sqlite3, tempfile
from pathlib import Path

def migrate(source, destination):
    source, destination = Path(source), Path(destination)
    if not source.is_file() or source.is_symlink():
        raise ValueError("Source account database missing or symlink")
    if destination.exists() or destination.is_symlink():
        raise ValueError("Destination exists; refusing overwrite")
    if not destination.parent.is_dir():
        raise ValueError("Destination directory missing")
    if destination.parent.stat().st_mode & 0o002:
        raise ValueError("Destination directory world-writable")
    fd, temp = tempfile.mkstemp(prefix='.accounts-migration-',suffix='.sqlite',dir=str(destination.parent))
    try:
        os.fchmod(fd,0o600)
        os.close(fd)
        with sqlite3.connect('file:'+str(source.resolve())+'?mode=ro',uri=True) as old, sqlite3.connect(temp) as new:
            old.backup(new)
            result = new.execute('PRAGMA integrity_check').fetchone()[0]
            if result != 'ok': raise ValueError('Database integrity check failed')
            tables={r[0] for r in new.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'users','sessions'}.issubset(tables): raise ValueError('Not a recognized accounts database')
            if new.execute('SELECT COUNT(*) FROM users').fetchone()[0] < 1: raise ValueError('No users in source')
        if destination.exists() or destination.is_symlink(): raise ValueError('Destination appeared during migration')
        os.link(temp,destination)
        return True
    finally:
        if os.path.exists(temp): os.unlink(temp)

if __name__=='__main__':
    p=argparse.ArgumentParser(description='Copy account DB without overwriting existing accounts')
    p.add_argument('--source',required=True);p.add_argument('--destination',required=True)
    a=p.parse_args();migrate(a.source,a.destination)
    print('Account database copied successfully; original unchanged')
