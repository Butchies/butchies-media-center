#!/usr/bin/env python3
"""Account database backup and one-time adoption of the RC20 test database.

  db_maintenance.py backup <data dir> [keep]
      Consistent copy of accounts.sqlite (SQLite backup API, integrity-checked)
      into <data dir>/backups/, keeping the newest <keep> copies (default 5).
  db_maintenance.py snapshot <data dir> <from version> <to version> [keep]
      Before an update: integrity-checked copies of ALL databases (accounts.sqlite,
      library.sqlite) into <data dir>/backups/update-<time>-from-<version>/ with a
      SHA-256 manifest and restore.sh (puts exactly these files back, e.g. for a
      return to the previous version). Keeps the newest <keep> sets (default 5).
  db_maintenance.py adopt-legacy <data dir> <legacy accounts.sqlite>
      If the app has no account database yet, copy the old one (read-only,
      original stays unchanged). Never overwrites an existing database.
"""
import hashlib, os, re, sqlite3, sys, time
from pathlib import Path
from migrate_accounts import migrate


def backup(data_dir, keep=5):
    data_dir = Path(data_dir)
    source = data_dir / 'accounts.sqlite'
    if not source.is_file() or source.is_symlink():
        return None
    target_dir = data_dir / 'backups'
    if target_dir.is_symlink():
        raise ValueError('backup directory is a symlink')
    target_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(str(target_dir), 0o700)
    # Fixed-width names sort chronologically: accounts-YYYYmmdd-HHMMSS-uuuuuu.sqlite
    now = time.time()
    stamp = time.strftime('%Y%m%d-%H%M%S', time.localtime(now))
    micro = int((now % 1) * 1000000)
    target = target_dir / ('accounts-%s-%06d.sqlite' % (stamp, micro))
    while target.exists():
        micro = (micro + 1) % 1000000
        target = target_dir / ('accounts-%s-%06d.sqlite' % (stamp, micro))
    temp = target.with_suffix('.tmp')
    try:
        with sqlite3.connect('file:%s?mode=ro' % source.resolve(), uri=True) as src, sqlite3.connect(str(temp)) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('integrity check failed')
        os.chmod(str(temp), 0o600)
        os.replace(str(temp), str(target))
    finally:
        if temp.exists():
            temp.unlink()
    for old in sorted(target_dir.glob('accounts-*.sqlite'))[:-keep]:
        old.unlink()
    return target


DATABASES = ('accounts.sqlite', 'library.sqlite')
RESTORE_SH = """#!/bin/sh
# Butchies Media Center: put back the databases saved before the update
# (from {from_version} to {to_version}, {created}).
# Use it after re-installing version {from_version}: the newer database format cannot be read
# by older versions. Media files, Emby and other apps are never touched.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd -P)
DATA="{data_dir}"
APP="${{BMC_APP:-/mnt/HD/HD_a2/Nas_Prog/butchiesmediacenter}}"
[ "$HERE" = "$DATA/backups/{name}" ] || {{ echo "restore.sh must stay in its backup folder" >&2; exit 1; }}
for f in {files}; do
 [ -f "$HERE/$f" ] || {{ echo "missing $f in backup" >&2; exit 1; }}
done
if command -v sha256sum >/dev/null 2>&1; then (cd "$HERE" && sha256sum -c MANIFEST.sha256) || {{ echo "backup damaged, nothing restored" >&2; exit 1; }}; fi
# Stop only this app's own server (stop.sh verifies the process via /proc).
if [ -f "$APP/stop.sh" ]; then BMC_DATA="$DATA" sh "$APP/stop.sh" "$APP" || {{ echo "could not stop the media center, nothing restored" >&2; exit 1; }}; fi
STAMP=$(date +%Y%m%d-%H%M%S)
for f in {files}; do
 if [ -f "$DATA/$f" ]; then cp -p "$DATA/$f" "$HERE/$f.replaced-$STAMP"; fi
 cp -p "$HERE/$f" "$DATA/$f.restore-tmp"
 chmod 600 "$DATA/$f.restore-tmp"
 mv "$DATA/$f.restore-tmp" "$DATA/$f"
done
echo "Restored: {files} (state before the update to {to_version})."
echo "The replaced newer files are kept here as *.replaced-$STAMP."
if [ -f "$APP/start.sh" ]; then BMC_DATA="$DATA" sh "$APP/start.sh" "$APP" && echo "Media center started."; fi
"""


def _sha256(path):
    h = hashlib.sha256()
    with open(str(path), 'rb') as f:
        for block in iter(lambda: f.read(1 << 16), b''): h.update(block)
    return h.hexdigest()


def recent_snapshot(data_dir, to_version, seconds):
    """Newest snapshot for the same target version made within the last <seconds>, if any."""
    backups = Path(data_dir) / 'backups'
    for folder in sorted(backups.glob('update-*'), reverse=True):
        try:
            info = dict(line.split('=', 1) for line in (folder / 'VERSION.txt').read_text().splitlines() if '=' in line)
        except OSError:
            continue
        if info.get('to') == to_version and time.time() - folder.stat().st_mtime < seconds:
            return folder
    return None


def snapshot(data_dir, from_version, to_version, keep=5, skip_if_recent=0):
    """Copy every existing database consistently before an update and write restore.sh."""
    data_dir = Path(data_dir)
    if skip_if_recent:
        existing = recent_snapshot(data_dir, to_version, skip_if_recent)
        if existing:
            return existing
    if data_dir.is_symlink() or not data_dir.is_dir():
        raise ValueError('data directory missing or a symlink')
    clean = lambda v: re.sub(r'[^0-9A-Za-z._-]', '_', v or 'unbekannt')[:40]
    sources = [n for n in DATABASES if (data_dir / n).is_file() and not (data_dir / n).is_symlink()]
    if not sources:
        return None
    backups = data_dir / 'backups'
    if backups.is_symlink():
        raise ValueError('backup directory is a symlink')
    backups.mkdir(mode=0o700, exist_ok=True)
    created = time.strftime('%Y-%m-%d %H:%M:%S')
    name = 'update-%s-from-%s' % (time.strftime('%Y%m%d-%H%M%S'), clean(from_version))
    target = backups / name
    n = 1
    while target.exists():
        target = backups / ('%s-%d' % (name, n)); n += 1
    temp = backups / ('.' + target.name + '.tmp')
    if temp.exists():
        raise ValueError('stale temporary backup folder ' + str(temp))
    temp.mkdir(mode=0o700)
    try:
        for db in sources:
            with sqlite3.connect('file:%s?mode=ro' % (data_dir / db).resolve(), uri=True) as src, sqlite3.connect(str(temp / db)) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('integrity check failed for ' + db)
            os.chmod(str(temp / db), 0o600)
        (temp / 'MANIFEST.sha256').write_text(''.join('%s  %s\n' % (_sha256(temp / db), db) for db in sources))
        (temp / 'VERSION.txt').write_text('from=%s\nto=%s\ncreated=%s\n' % (from_version, to_version, created))
        (temp / 'restore.sh').write_text(RESTORE_SH.format(from_version=clean(from_version), to_version=clean(to_version), created=created,
                                                          data_dir=str(data_dir.resolve()), name=target.name, files=' '.join(sources)))
        os.chmod(str(temp / 'restore.sh'), 0o700)
        os.rename(str(temp), str(target))
    except BaseException:
        for f in temp.glob('*'): f.unlink()
        temp.rmdir()
        raise
    sets = sorted(p for p in backups.glob('update-*') if p.is_dir() and not p.is_symlink())
    for old in sets[:-keep]:
        for f in old.iterdir(): f.unlink()
        old.rmdir()
    return target


def adopt_legacy(data_dir, legacy):
    data_dir, legacy = Path(data_dir), Path(legacy)
    destination = data_dir / 'accounts.sqlite'
    if destination.exists() or destination.is_symlink():
        return 'skipped: app already has an account database'
    if not legacy.is_file() or legacy.is_symlink():
        return 'skipped: no legacy database'
    data_dir.mkdir(parents=True, exist_ok=True)
    migrate(legacy, destination)
    os.chmod(str(destination), 0o600)
    return 'adopted accounts from %s (original unchanged)' % legacy


if __name__ == '__main__':
    try:
        if len(sys.argv) >= 3 and sys.argv[1] == 'backup':
            result = backup(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 5)
            print('backup:', result or 'nothing to back up')
        elif len(sys.argv) >= 5 and sys.argv[1] == 'snapshot':
            # optional 5th argument: skip when a snapshot for the same target is younger than N seconds
            result = snapshot(sys.argv[2], sys.argv[3], sys.argv[4], skip_if_recent=int(sys.argv[5]) if len(sys.argv) > 5 else 0)
            print('snapshot:', result or 'no databases yet')
        elif len(sys.argv) == 4 and sys.argv[1] == 'adopt-legacy':
            print('legacy:', adopt_legacy(sys.argv[2], sys.argv[3]))
        else:
            print(__doc__); sys.exit(2)
    except (ValueError, OSError, sqlite3.Error) as e:
        print('ERROR:', e, file=sys.stderr); sys.exit(1)
