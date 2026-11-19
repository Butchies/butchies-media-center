"""Updates from GitHub releases, installed on request of an administrator (Python 3.9 stdlib).

Flow (POST /api/admin/update/install):
 1. Read the latest release of the private repository with the read-only token stored on the NAS.
 2. Download butchiesmediacenter_<version>_update.tar.gz and its .sha256 from that release.
 3. Check size, SHA-256, every archive member (no links, no absolute paths, no '..'), the version in
    apkg.rc and that all Python files compile.
 4. Hand over to self_update.sh from the new package, which runs in its own session: install.sh
    (stops this server, backs up all databases, swaps the program folder and keeps the old one),
    then init.sh and start.sh. If the new version does not start, the old program folder and the
    databases are put back and the old version is started again.

Media files, Emby and other apps are never touched. The token is never logged, never sent to the
browser and never sent anywhere except the GitHub API.
"""
import hashlib, json, os, re, shutil, subprocess, tarfile, tempfile, threading, time
import urllib.error, urllib.parse, urllib.request
from pathlib import Path

REPO = 'Butchies/butchies-media-center'
# Only the test suite points this at a local fake API.
API = os.environ.get('BMC_GITHUB_API', 'https://api.github.com').rstrip('/')
NAME = 'butchiesmediacenter'
ARCHIVE_RE = re.compile(r'butchiesmediacenter_(\d+\.\d+\.\d+)_update\.tar\.gz')
TOKEN_RE = re.compile(r'(?:github_pat_[A-Za-z0-9_]{20,255}|gh[pousr]_[A-Za-z0-9]{20,255})')
DOWNLOAD_HOSTS = frozenset(('github.com', 'api.github.com', 'objects.githubusercontent.com',
                            'release-assets.githubusercontent.com'))
MAX_ARCHIVE = 40 * 1024 * 1024
MAX_UNPACKED = 120 * 1024 * 1024
MAX_MEMBERS = 2000
REQUIRED = ('server.py', 'auth.py', 'updater.py', 'apkg.rc', 'install.sh', 'install_app.sh', 'start.sh', 'stop.sh',
            'init.sh', 'wd_env.sh', 'self_update.sh', 'db_maintenance.py', 'web/index.html', 'web/app.js')

job_lock = threading.Lock()
job = {'state': 'idle'}


class UpdateError(Exception):
    """Failure with a message that is safe to show to the administrator."""


# -- token ------------------------------------------------------------------------------------
def token_file(data):
    return Path(data) / 'github_token'


def load_token(data):
    try:
        value = token_file(data).read_text().strip()
        if TOKEN_RE.fullmatch(value): return value
    except OSError:
        pass
    value = os.environ.get('BMC_GITHUB_TOKEN', '').strip()
    return value if TOKEN_RE.fullmatch(value) else ''


def save_token(data, value):
    """Store (or with an empty value remove) the token; readable by the app only (0600)."""
    path = token_file(data)
    value = (value or '').strip()
    if not value:
        try: path.unlink()
        except FileNotFoundError: pass
        return False
    if not TOKEN_RE.fullmatch(value):
        raise UpdateError('Das sieht nicht wie ein GitHub-Token aus (beginnt mit github_pat_ oder ghp_).')
    Path(data).mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f: f.write(value + '\n')
    os.chmod(str(tmp), 0o600)
    os.replace(str(tmp), str(path))
    return True


# -- versions ---------------------------------------------------------------------------------
def parse_version(text):
    m = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', str(text or '').strip())
    return tuple(int(x) for x in m.groups()) if m else None


def installed_version(app_dir):
    try:
        m = re.search(r'^Version:\s*(\S+)', (Path(app_dir) / 'apkg.rc').read_text(), re.M)
    except OSError:
        return ''
    return m.group(1) if m and parse_version(m.group(1)) else ''


# -- GitHub API -------------------------------------------------------------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _headers(token, accept):
    return {'Authorization': 'Bearer ' + token, 'Accept': accept, 'User-Agent': 'ButchiesMediaCenter/Updater',
            'X-GitHub-Api-Version': '2022-11-28'}


def _http_error(code):
    if code in (401, 403):
        return UpdateError('GitHub hat den Token abgelehnt (ungültig, abgelaufen oder ohne Leserecht für das Repository).')
    if code == 404:
        return UpdateError('Kein Release gefunden. Entweder gibt es noch keinen, oder der Token hat keinen Zugriff auf das Repository.')
    return UpdateError('GitHub antwortet mit Fehler %d.' % code)


def api_json(path, token, limit=262144):
    req = urllib.request.Request(API + path, headers=_headers(token, 'application/vnd.github+json'))
    try:
        with _opener.open(req, timeout=15) as resp:
            body = resp.read(limit + 1)
    except urllib.error.HTTPError as e:
        raise _http_error(e.code)
    except (OSError, urllib.error.URLError):
        raise UpdateError('GitHub ist nicht erreichbar (Internetverbindung des NAS prüfen).')
    if len(body) > limit: raise UpdateError('Antwort von GitHub zu groß.')
    try:
        return json.loads(body)
    except ValueError:
        raise UpdateError('Ungültige Antwort von GitHub.')


def latest_release(token):
    release = api_json('/repos/%s/releases/latest' % REPO, token)
    if not isinstance(release, dict): raise UpdateError('Ungültige Antwort von GitHub.')
    tag = release.get('tag_name')
    version = parse_version(tag)
    if not version: raise UpdateError('Der neueste Release hat keine gültige Versionsnummer.')
    archive = checksum = None
    for asset in release.get('assets') or []:
        if not isinstance(asset, dict): continue
        name, asset_id, size = asset.get('name'), asset.get('id'), asset.get('size')
        if not isinstance(name, str) or not isinstance(asset_id, int): continue
        m = ARCHIVE_RE.fullmatch(name)
        if m and parse_version(m.group(1)) == version and isinstance(size, int) and 0 < size <= MAX_ARCHIVE:
            archive = {'id': asset_id, 'name': name, 'size': size}
    if archive:
        for asset in release.get('assets') or []:
            if isinstance(asset, dict) and asset.get('name') == archive['name'] + '.sha256' and isinstance(asset.get('id'), int):
                checksum = {'id': asset['id'], 'name': asset['name']}
    return {'version': '%d.%d.%d' % version, 'tag': tag, 'archive': archive, 'checksum': checksum,
            'notes': str(release.get('body') or '')[:2000]}


def _allowed_download(url):
    parts = urllib.parse.urlsplit(url)
    api = urllib.parse.urlsplit(API)
    if parts.username or parts.password or not parts.hostname: return False
    if parts.scheme == 'https' and (parts.hostname in DOWNLOAD_HOSTS or parts.hostname.endswith('.githubusercontent.com')): return True
    # Only the local fake API of the test suite: same scheme and host as the API.
    return API != 'https://api.github.com' and parts.scheme == api.scheme and parts.hostname == api.hostname


def download_asset(asset, token, limit, dest):
    """Stream a release asset to dest; returns its SHA-256. The token is sent to the API only:
    GitHub answers with a redirect to a signed storage URL that is fetched without it."""
    req = urllib.request.Request('%s/repos/%s/releases/assets/%d' % (API, REPO, asset['id']),
                                 headers=_headers(token, 'application/octet-stream'))
    try:
        resp = _opener.open(req, timeout=30)
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 303, 307, 308): raise _http_error(e.code)
        location = e.headers.get('Location', '')
        if not _allowed_download(location): raise UpdateError('GitHub hat auf eine unerwartete Adresse umgeleitet.')
        try:
            resp = _opener.open(urllib.request.Request(location, headers={'User-Agent': 'ButchiesMediaCenter/Updater',
                                                                          'Accept': 'application/octet-stream'}), timeout=30)
        except urllib.error.HTTPError as e2:
            raise UpdateError('Download fehlgeschlagen (Fehler %d).' % e2.code)
        except (OSError, urllib.error.URLError):
            raise UpdateError('Download fehlgeschlagen (Verbindung unterbrochen).')
    except (OSError, urllib.error.URLError):
        raise UpdateError('GitHub ist nicht erreichbar (Internetverbindung des NAS prüfen).')
    digest, total = hashlib.sha256(), 0
    try:
        with resp, open(str(dest), 'wb') as out:
            while True:
                block = resp.read(65536)
                if not block: break
                total += len(block)
                if total > limit: raise UpdateError('Update-Datei ist größer als erlaubt.')
                digest.update(block); out.write(block)
    except OSError:
        raise UpdateError('Download fehlgeschlagen (Verbindung unterbrochen).')
    return digest.hexdigest()


# -- package checks ---------------------------------------------------------------------------
def safe_extract(archive, target):
    """Unpack only regular files and folders below butchiesmediacenter/."""
    target = Path(target)
    total = 0
    try:
        tar = tarfile.open(str(archive), mode='r:gz')
    except (tarfile.TarError, OSError):
        raise UpdateError('Update-Datei ist kein gültiges Archiv.')
    with tar:
        members = tar.getmembers()
        if len(members) > MAX_MEMBERS: raise UpdateError('Update-Datei enthält zu viele Einträge.')
        for m in members:
            parts = m.name.split('/')
            if m.name.startswith('/') or '\\' in m.name or '..' in parts or parts[0] != NAME:
                raise UpdateError('Update-Datei enthält einen unzulässigen Pfad: %s' % m.name[:120])
            if not (m.isfile() or m.isdir()):
                raise UpdateError('Update-Datei enthält einen Link oder eine Sonderdatei: %s' % m.name[:120])
            total += max(0, m.size)
            if total > MAX_UNPACKED: raise UpdateError('Update-Datei ist entpackt zu groß.')
        for m in members:
            path = target.joinpath(*[p for p in m.name.split('/') if p not in ('', '.')])
            if m.isdir():
                path.mkdir(parents=True, exist_ok=True); continue
            path.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(m)
            with src, open(str(path), 'wb') as out: shutil.copyfileobj(src, out)
            os.chmod(str(path), 0o755 if m.name.endswith('.sh') else 0o644)
    return target / NAME


def verify_package(package, version):
    package = Path(package)
    for rel in REQUIRED:
        if not (package / rel).is_file(): raise UpdateError('Update unvollständig: %s fehlt.' % rel)
    if installed_version(package) != version:
        raise UpdateError('Versionsnummer im Paket passt nicht zum Release %s.' % version)
    for py in package.rglob('*.py'):
        try:
            compile(py.read_bytes(), str(py), 'exec', dont_inherit=True)
        except (SyntaxError, ValueError):
            raise UpdateError('Update enthält fehlerhaften Programmcode (%s).' % py.name)


# -- job --------------------------------------------------------------------------------------
def status_file(data):
    return Path(data) / 'update' / 'status.json'


def write_status(data, **values):
    values.setdefault('time', int(time.time()))
    with job_lock:
        job.clear(); job.update(values)
    path = status_file(data)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name('status.json.tmp')
        tmp.write_text(json.dumps(values))
        os.replace(str(tmp), str(path))
    except OSError:
        pass


def read_status(data):
    """Last job state; after a restart it comes from the file written by self_update.sh."""
    with job_lock:
        if job.get('state') in ('downloading', 'verifying', 'handover'): return dict(job)
    try:
        value = json.loads(status_file(data).read_text())
        if isinstance(value, dict) and isinstance(value.get('state'), str):
            # A handover that never finished (for example a power cut) must not look busy forever.
            if value['state'] in ('handover', 'installing', 'rollback') and time.time() - float(value.get('time') or 0) > 900:
                value = dict(value, state='failed', message='Das Update wurde nicht abgeschlossen. Details: Status und Diagnose im WD-Dashboard.')
            return value
    except (OSError, ValueError):
        pass
    return {'state': 'idle'}


def running():
    with job_lock:
        return job.get('state') in ('downloading', 'verifying', 'handover')


def prepare(data, app_dir, token, expected):
    """Download and check the release; returns the folder of the verified new package."""
    data, app_dir = Path(data), Path(app_dir)
    release = latest_release(token)
    if release['version'] != expected:
        raise UpdateError('Auf GitHub ist inzwischen eine andere Version (%s). Bitte erneut prüfen.' % release['version'])
    current = parse_version(installed_version(app_dir))
    if not current or parse_version(release['version']) <= current:
        raise UpdateError('Version %s ist nicht neuer als die installierte.' % release['version'])
    if not release['archive'] or not release['checksum']:
        raise UpdateError('Der Release %s enthält kein Update-Paket.' % release['version'])
    work = data / 'update'
    work.mkdir(parents=True, exist_ok=True)
    for old in work.glob('stage-*'): shutil.rmtree(str(old), ignore_errors=True)
    fd, sums = tempfile.mkstemp(prefix='sha-', dir=str(work)); os.close(fd)
    fd, archive = tempfile.mkstemp(prefix='download-', suffix='.tar.gz', dir=str(work)); os.close(fd)
    try:
        download_asset(release['checksum'], token, 4096, sums)
        m = re.match(r'([0-9a-f]{64})\s+\*?(\S+)', Path(sums).read_text(errors='replace').strip())
        if not m or m.group(2) != release['archive']['name']:
            raise UpdateError('Prüfsummendatei im Release ist ungültig.')
        write_status(data, state='downloading', version=release['version'], message='Lade Version %s …' % release['version'])
        actual = download_asset(release['archive'], token, MAX_ARCHIVE, archive)
        write_status(data, state='verifying', version=release['version'], message='Prüfe Version %s …' % release['version'])
        if actual != m.group(1):
            raise UpdateError('Prüfsumme stimmt nicht – Download beschädigt. Es wurde nichts verändert.')
        stage = Path(tempfile.mkdtemp(prefix='stage-', dir=str(work)))
        package = safe_extract(archive, stage)
        verify_package(package, release['version'])
        return package, release['version']
    finally:
        for f in (sums, archive):
            try: os.unlink(f)
            except OSError: pass


def handover(data, app_dir, package, version):
    """Start self_update.sh detached: it stops this server as part of the installation."""
    log = open(str(Path(data) / 'update' / 'self_update.log'), 'ab')
    env = dict(os.environ, BMC_DATA=str(data))
    subprocess.Popen(['sh', str(Path(package) / 'self_update.sh'), str(app_dir), str(package)], env=env,
                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
    log.close()


def start(data, app_dir, expected):
    """Run the whole update in a background thread. Returns False if one is already running."""
    with job_lock:
        if job.get('state') in ('downloading', 'verifying', 'handover'): return False
        job.clear(); job.update(state='downloading', version=expected, message='Verbinde mit GitHub …', time=int(time.time()))
    token = load_token(data)

    def worker():
        try:
            if not token: raise UpdateError('Kein GitHub-Token eingerichtet.')
            package, version = prepare(data, app_dir, token, expected)
            write_status(data, state='handover', version=version,
                         message='Installiere Version %s, der Media Center startet gleich neu …' % version)
            handover(data, app_dir, package, version)
        except UpdateError as e:
            write_status(data, state='failed', version=expected, message=str(e))
        except Exception:
            write_status(data, state='failed', version=expected, message='Unerwarteter Fehler beim Update. Es wurde nichts verändert.')

    threading.Thread(target=worker, daemon=True).start()
    return True
