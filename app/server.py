#!/usr/bin/env python3
"""Butchies Media Center NAS preview server, Python 3.9 stdlib."""
import os, json, mimetypes, secrets, hashlib, hmac, sqlite3, socket, urllib.parse, urllib.request, urllib.error, re, time, threading, stat
from auth import Accounts
import updater
import jf_api
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('BMC_DATA',str(ROOT/'data')))
MEDIA=Path(os.environ.get('BMC_MEDIA','/mnt/HD/HD_a2/Public'))
PORT=int(os.environ.get('BMC_PORT','8097'))
TOKEN=os.environ.get('BMC_TOKEN','')
BIND=os.environ.get('BMC_BIND','127.0.0.1')
TLS_CERT=os.environ.get('BMC_TLS_CERT','')
TLS_KEY=os.environ.get('BMC_TLS_KEY','')
SETUP_CODE_FILE=Path(os.environ.get('BMC_SETUP_CODE_FILE',str(MEDIA/'Butchies_Media_Center_Einrichtungscode.txt')))
setup_code_hash=None
setup_lock=threading.Lock()
VERSION='3.10.0'
# Explicit host allowlist for a future trusted TLS reverse proxy.
# Empty by default: no LAN hostname is trusted implicitly.
EXTRA_HOSTS=frozenset(x.strip().lower() for x in os.environ.get('BMC_ALLOWED_HOSTS','').split(',') if x.strip())
accounts=None
playback_tickets={}
playback_lock=threading.Lock()
login_attempts={}
login_lock=threading.Lock()
scan_lock=threading.Lock()
# Candidate file signatures persist across automatic scan cycles.
pending_media_signatures={}
# A new or changed file is indexed once it has not been written to for this many seconds
# (ctime, which copy tools cannot backdate) or once it is unchanged across two scans.
STABLE_SECONDS=max(0,int(os.environ.get('BMC_STABLE_SECONDS','60')))
AUTO_SCAN_SECONDS=max(60,int(os.environ.get('BMC_AUTO_SCAN_SECONDS','300')))
# Never remove this many index entries at once without an explicit admin confirmation.
MASS_REMOVAL_MIN=20
scan_status_lock=threading.Lock()
scan_status={'state':'idle','trigger':None,'started':None,'finished':None,'duration':None,'checked':0,'indexed':0,
 'new':0,'updated':0,'deferred':0,'removed':0,'removal_blocked':0,'errors':[],'warning':'','result':None}
EXT={'.mp4','.mkv','.avi','.mov','.webm','.m4v','.mp3','.flac','.m4a','.wav','.ogg'}
VIDEO={'.mp4','.mkv','.avi','.mov','.webm','.m4v'}
MIME={'.mkv':'video/x-matroska','.avi':'video/x-msvideo','.flac':'audio/flac'}
from contextlib import contextmanager

@contextmanager
def sqlite_session(db_path):
    """Commit on success, roll back on failure, and always close the connection."""
    connection = sqlite3.connect(str(db_path), timeout=15)
    connection.execute('PRAGMA busy_timeout=15000')
    try:
        with connection:
            yield connection
    finally:
        connection.close()

def init():
 DATA.mkdir(parents=True,exist_ok=True)
 with sqlite_session(DATA/'library.sqlite') as c:
  c.execute('CREATE TABLE IF NOT EXISTS media (id TEXT PRIMARY KEY,path TEXT UNIQUE,title TEXT,kind TEXT,bytes INTEGER, width INTEGER,height INTEGER)')
  media_columns={row[1] for row in c.execute('PRAGMA table_info(media)')}
  # Change detection so unchanged files are not re-read on every scan (RC33).
  if 'mtime_ns' not in media_columns:c.execute('ALTER TABLE media ADD COLUMN mtime_ns INTEGER')
  if 'sidecar_ns' not in media_columns:c.execute('ALTER TABLE media ADD COLUMN sidecar_ns INTEGER')
  # Cover artwork found during the scan, so requests do not search the disk (RC33).
  if 'cover_path' not in media_columns:c.execute('ALTER TABLE media ADD COLUMN cover_path TEXT')
  if 'cover_ns' not in media_columns:c.execute('ALTER TABLE media ADD COLUMN cover_ns INTEGER')
  # Libraries (phase 2): named collections of folders below MEDIA with a category.
  if 'library_id' not in media_columns:c.execute('ALTER TABLE media ADD COLUMN library_id INTEGER')
  c.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
  c.execute('CREATE TABLE IF NOT EXISTS libraries (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE COLLATE NOCASE, category TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, position INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL DEFAULT 0, updated INTEGER NOT NULL DEFAULT 0)')
  c.execute('CREATE TABLE IF NOT EXISTS library_folders (library_id INTEGER NOT NULL, path TEXT NOT NULL, PRIMARY KEY(library_id,path))')
  if not c.execute("SELECT 1 FROM settings WHERE key='libraries_migrated'").fetchone():
   # Nutzerwunsch 19.11.2026: keine automatische Bibliothek über den ganzen Medienordner –
   # der Nutzer bestimmt selbst, welche Ordner freigegeben werden (Dashboard → Bibliotheken).
   c.execute("INSERT INTO settings(key,value) VALUES('libraries_migrated','1')")
  default=c.execute('SELECT MIN(id) FROM libraries').fetchone()[0]
  if default is not None:c.execute('UPDATE media SET library_id=? WHERE library_id IS NULL',(default,))
  c.execute('CREATE TABLE IF NOT EXISTS media_stream_cache (media_id TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, payload TEXT NOT NULL)')
  c.execute('CREATE TABLE IF NOT EXISTS media_details (media_id TEXT PRIMARY KEY, custom_title TEXT NOT NULL DEFAULT \'\', description TEXT NOT NULL DEFAULT \'\', year INTEGER)')
  columns={row[1] for row in c.execute('PRAGMA table_info(media_details)')}
  if 'genre' not in columns:c.execute("ALTER TABLE media_details ADD COLUMN genre TEXT NOT NULL DEFAULT ''")
  if 'rating' not in columns:c.execute('ALTER TABLE media_details ADD COLUMN rating REAL')
  c.execute('CREATE TABLE IF NOT EXISTS playback_progress (user_id INTEGER NOT NULL, media_id TEXT NOT NULL, position INTEGER NOT NULL, duration INTEGER NOT NULL, updated INTEGER NOT NULL, PRIMARY KEY(user_id,media_id))')
  if 'completed' not in {row[1] for row in c.execute('PRAGMA table_info(playback_progress)')}:c.execute('ALTER TABLE playback_progress ADD COLUMN completed INTEGER NOT NULL DEFAULT 0')
def probe(path):
 import subprocess
 binary=ROOT/'bin'/'ffprobe'
 if not binary.is_file():
  import shutil
  located=shutil.which('ffprobe')
  if not located:
   # No ffprobe on the NAS: read width/height from the container header instead.
   import videoinfo
   return videoinfo.probe(path)
  binary=Path(located)
 try:
  p=subprocess.run([str(binary),'-v','quiet','-select_streams','v:0','-show_entries','stream=width,height','-of','json',str(path)],capture_output=True,timeout=12)
  x=json.loads(p.stdout.decode());v=x.get('streams',[{}])[0];return v.get('width'),v.get('height')
 except Exception:return None,None
SETUP_ALPHABET='ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
def prepare_setup_code():
 """While no administrator exists, create a one-time setup code and write it to a file
 the owner can open from the NAS share. Returns the code, or None if setup is complete."""
 global setup_code_hash
 if accounts.count():
  clear_setup_code();return None
 code=''.join(secrets.choice(SETUP_ALPHABET) for _ in range(10))
 setup_code_hash=hashlib.sha256(code.encode()).hexdigest()
 try:
  if SETUP_CODE_FILE.is_symlink():SETUP_CODE_FILE.unlink()
  SETUP_CODE_FILE.write_text('Butchies Media Center - Einrichtungscode\r\n\r\n'+code+'\r\n\r\n'
   'Im Browser die Adresse des Media Centers oeffnen (Port 8097) und diesen Code bei\r\n'
   '"Administrator einrichten" eingeben. Die Datei wird danach automatisch geloescht.\r\n',encoding='utf-8')
  os.chmod(str(SETUP_CODE_FILE),0o644)
 except OSError as e:print('Setup code file could not be written:',e,flush=True)
 print('Setup required. Setup code written to',SETUP_CODE_FILE,flush=True)
 return code
def clear_setup_code():
 global setup_code_hash
 setup_code_hash=None
 try:
  if SETUP_CODE_FILE.exists() or SETUP_CODE_FILE.is_symlink():SETUP_CODE_FILE.unlink()
 except OSError:pass
def import_local_nfo(connection, media_id, media_path):
 """Import local Kodi/Emby-style XML metadata only when no manual metadata exists."""
 import xml.etree.ElementTree as ET
 source=Path(media_path)
 # Prefer episode-specific metadata; movie.nfo is only valid for films.
 is_episode=bool(re.search(r'(?i)(?:^|[ ._-])s[0-9]{1,2}[ ._-]*e[0-9]{1,3}(?:$|[ ._-])|(?:^|[ ._-])[0-9]{1,2}x[0-9]{1,3}(?:$|[ ._-])',source.stem))
 candidates=(source.with_suffix('.nfo'),) if is_episode else (source.with_suffix('.nfo'),source.parent/'movie.nfo')
 for candidate in candidates:
  try:
   if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size>256*1024:continue
   if MEDIA.resolve() not in candidate.resolve(strict=True).parents:continue
   root=ET.parse(str(candidate)).getroot()
   if root.tag not in ('movie','episodedetails','musicvideo'):continue
   def value(tag,limit):
    element=root.find(tag)
    return (element.text or '').strip()[:limit] if element is not None else ''
   title=value('title',180) or value('originaltitle',180)
   description=value('plot',2000) or value('outline',2000)
   genre=value('genre',100)
   raw_year=value('year',4)
   if not raw_year:
    # Kodi NFO files often contain premiered/releasedate instead of year.
    date_text=value('premiered',32) or value('releasedate',32)
    match_year=re.match(r'^(\d{4})(?:[-/]|$)',date_text)
    raw_year=match_year.group(1) if match_year else ''
   year=int(raw_year) if raw_year.isdigit() and 1888<=int(raw_year)<=2200 else None
   raw_rating=value('rating',16)
   try:rating=float(raw_rating);rating=rating if 0<=rating<=10 else None
   except ValueError:rating=None
   if not any((title,description,genre,year,rating)):return
   connection.execute('INSERT OR IGNORE INTO media_details(media_id,custom_title,description,year,genre,rating) VALUES(?,?,?,?,?,?)',(media_id,title,description,year,genre,rating))
   return
  except (OSError,ET.ParseError,ValueError):continue

LIBRARY_CATEGORIES={'movies':'Filme','series':'Serien','music':'Musik','mixed':'Gemischt'}
AUDIO=EXT-VIDEO
def category_extensions(category):
 return VIDEO if category in ('movies','series') else AUDIO if category=='music' else EXT
def normalize_library_folder(raw):
 """Validate a library folder given relative to MEDIA. Returns the normalized relative path
 ('' = whole media folder) or raises ValueError. Never follows symlinks or leaves MEDIA."""
 if not isinstance(raw,str) or len(raw)>400 or '\x00' in raw:raise ValueError('INVALID_FOLDER')
 text=raw.strip().replace('\\','/').strip('/')
 parts=[part for part in text.split('/')] if text else []
 for part in parts:
  if part in ('','.','..') or part.startswith('.'):raise ValueError('INVALID_FOLDER')
 root=MEDIA.resolve()
 current=root
 for part in parts:
  current=current/part
  if current.is_symlink():raise ValueError('FOLDER_IS_SYMLINK')
 if not current.is_dir():raise ValueError('FOLDER_NOT_FOUND')
 resolved=current.resolve(strict=True)
 if resolved!=root and root not in resolved.parents:raise ValueError('INVALID_FOLDER')
 return '/'.join(parts)
def folders_overlap(a,b):
 # '' (whole media folder) overlaps everything; otherwise equal or nested at a path boundary.
 return a==b or a=='' or b=='' or b.startswith(a+'/') or a.startswith(b+'/')
def library_rows(c,enabled_only=False):
 rows=c.execute('SELECT id,name,category,enabled,position FROM libraries'+(' WHERE enabled=1' if enabled_only else '')+' ORDER BY position,name COLLATE NOCASE').fetchall()
 folders={}
 for library_id,path in c.execute('SELECT library_id,path FROM library_folders ORDER BY path'):folders.setdefault(library_id,[]).append(path)
 return [{'id':r[0],'name':r[1],'category':r[2],'enabled':bool(r[3]),'position':r[4],'folders':folders.get(r[0],[])} for r in rows]
def validate_library(c,data,library_id=None):
 """Check name, category and folders of a library to create/update; returns clean values."""
 name=data.get('name');category=data.get('category');folders=data.get('folders');enabled=data.get('enabled',True)
 if not isinstance(name,str) or not 1<=len(name.strip())<=60 or any(ord(ch)<32 for ch in name):raise ValueError('INVALID_NAME')
 name=name.strip()
 if category not in LIBRARY_CATEGORIES:raise ValueError('INVALID_CATEGORY')
 if not isinstance(enabled,bool):raise ValueError('INVALID_ENABLED')
 if not isinstance(folders,list) or not 1<=len(folders)<=20:raise ValueError('INVALID_FOLDERS')
 clean=[]
 for raw in folders:
  folder=normalize_library_folder(raw)
  for other in clean:
   if folders_overlap(folder,other):raise ValueError('FOLDERS_OVERLAP')
  clean.append(folder)
 for other in library_rows(c):
  if other['id']==library_id:continue
  if other['name'].lower()==name.lower():raise ValueError('NAME_EXISTS')
  for theirs in other['folders']:
   for mine in clean:
    # Wie Jellyfin: ein Unterordner darf eine eigene Bibliothek sein (die genauere gewinnt), nur derselbe Ordner nicht.
    if mine==theirs:raise ValueError('FOLDER_USED:'+other['name'])
 return name,category,sorted(clean),enabled
def prune_library_index(c,library_id,category,folders):
 """Drop index rows (never files) of a library that are no longer inside its folders or no
 longer match its category. Custom metadata and progress stay keyed by media id."""
 root=str(MEDIA.resolve())
 removed=0
 for ident,path in c.execute('SELECT id,path FROM media WHERE library_id=?',(library_id,)).fetchall():
  rel=os.path.relpath(path,root).replace(os.sep,'/')
  inside=any(f=='' or rel.startswith(f+'/') for f in folders)
  if not inside or Path(path).suffix.lower() not in category_extensions(category):
   c.execute('DELETE FROM media WHERE id=?',(ident,));removed+=1
 return removed
SERIES_RE=re.compile(r'(?i)(?:^|[ ._-])s([0-9]{1,2})[ ._-]*e([0-9]{1,3})(?:$|[ ._-])|(?:^|[ ._-])([0-9]{1,2})x([0-9]{1,3})(?:$|[ ._-])')
SEASON_FOLDER_RE=re.compile(r'(?i)(?:season|staffel|s)[ _.-]*([0-9]+)')
def classify_item(x,stem,library_folder_parts):
 """Category/series/season/episode for a library item. The library category decides;
 only 'mixed' libraries use filename detection (the behaviour before phase 2)."""
 category=x.get('library_category') or 'mixed'
 x['series']=None;x['season']=None;x['episode']=None
 if x['kind']=='audio':
  x['category']='music';return
 match=SERIES_RE.search(stem)
 if category=='movies' or (category=='mixed' and not match):
  x['category']='movie';return
 x['category']='series'
 folders=[part for part in x['folder'].replace(chr(92),'/').split('/') if part and part!='Hauptordner']
 if match:
  x['season']=int(match.group(1) or match.group(3))
  x['episode']=int(match.group(2) or match.group(4))
  name=stem[:match.start()].replace('.',' ').replace('_',' ').replace('-',' ').strip()
 else:
  name=''
  # Series library without SxxEyy: season from a "Staffel 2"/"Season 2" folder.
  for part in reversed(folders):
   season=SEASON_FOLDER_RE.fullmatch(part)
   if season:x['season']=int(season.group(1));break
 if not name or name.lower() in ('episode','folge'):
  inner=folders[len(library_folder_parts):] if folders[:len(library_folder_parts)]==library_folder_parts else folders
  candidates=[part for part in inner if not SEASON_FOLDER_RE.fullmatch(part) and part.lower() not in ('serien','series','tv shows','tv-serien')]
  # In a series library the first folder below the library root is the show.
  if category=='series':
   # Series library: the first folder below the library root is the show; files directly
   # in the library root fall back to their own title.
   name=candidates[0] if candidates else x['title']
  else:
   # Mixed library (behaviour before phase 2): nearest non-season folder.
   name=candidates[-1] if candidates else 'Unbekannte Serie'
 # Normalize common release suffixes so episodes from different seasons group together.
 name=re.sub(r'(?i)[ ._-]+(?:19|20)\d{2}$','',name).strip() or name
 x['series']=name
def library_items():
 with sqlite_session(DATA/'library.sqlite') as c:
  c.row_factory=sqlite3.Row
  items=[dict(x) for x in c.execute('SELECT m.id,m.path,COALESCE(NULLIF(d.custom_title,\'\'),m.title) AS title,m.kind,m.bytes,m.width,m.height,COALESCE(d.description,\'\') AS description,d.year,COALESCE(d.genre,\'\') AS genre,d.rating,CASE WHEN m.cover_path IS NULL THEN NULL ELSE CAST(COALESCE(m.cover_ns,0) AS TEXT) END AS cover,m.library_id,l.name AS library,l.category AS library_category FROM media m JOIN libraries l ON l.id=m.library_id AND l.enabled=1 LEFT JOIN media_details d ON d.media_id=m.id ORDER BY title LIMIT 1000')]
  folders={}
  for library_id,path in c.execute('SELECT library_id,path FROM library_folders'):folders.setdefault(library_id,[]).append(path)
 root=MEDIA.resolve()
 for x in items:
  try:
   relative=Path(x.pop('path')).relative_to(root)
   x['folder']=str(relative.parent) if str(relative.parent)!='.' else 'Hauptordner'
   stem=relative.stem
   rel_posix=relative.as_posix()
   own=[f for f in folders.get(x['library_id'],[]) if f=='' or rel_posix.startswith(f+'/')]
   library_parts=[part for part in (own[0] if own else '').split('/') if part]
  except ValueError:
   x.pop('path',None)
   x['folder']='Hauptordner'
   stem=x['title'];library_parts=[]
  classify_item(x,stem,library_parts)
  x['blocked']=x['kind']=='video' and (not x['width'] or not x['height'] or x['width']>1920 or x['height']>1080)
 return items
def _scan_update(**values):
 with scan_status_lock:scan_status.update(values)
def scan_status_snapshot(include_errors=True):
 with scan_status_lock:
  snapshot=dict(scan_status);snapshot['errors']=list(scan_status['errors']) if include_errors else []
 snapshot['auto_scan_seconds']=AUTO_SCAN_SECONDS;snapshot['stable_seconds']=STABLE_SECONDS
 return snapshot
def cover_candidates(source):
 # Only local sidecar artwork. No external services, uploads or image processing.
 # Episode thumbnails first, then season artwork, then show poster.
 match=re.search(r'(?i)(?:^|[ ._-])s([0-9]{1,2})[ ._-]*e[0-9]{1,3}(?:$|[ ._-])|(?:^|[ ._-])([0-9]{1,2})x[0-9]{1,3}(?:$|[ ._-])',source.stem)
 artwork=[source.with_suffix('.jpg'),source.with_suffix('.jpeg'),source.with_suffix('.png'),source.with_name(source.stem+'-poster.jpg'),source.with_name(source.stem+'-poster.png'),source.with_name(source.stem+'-thumb.jpg'),source.with_name(source.stem+'-thumb.png')]
 if match:
  season=int(match.group(1) or match.group(2))
  artwork.extend([source.parent/('season%02d-poster.jpg'%season),source.parent/('season%02d.jpg'%season),source.parent/'poster.jpg',source.parent/'folder.jpg'])
  artwork.extend([source.parent.parent/('season%02d-poster.jpg'%season),source.parent.parent/('season%02d.jpg'%season),source.parent.parent/'poster.jpg',source.parent.parent/'folder.jpg'])
 else:artwork.extend([source.parent/'poster.jpg',source.parent/'folder.jpg'])
 # Additional common local naming conventions, without external lookups.
 artwork.extend([source.parent/'cover.jpg',source.parent/'cover.png',source.parent/'poster.png',source.parent/'folder.png'])
 if match:
  season=int(match.group(1) or match.group(2))
  artwork.extend([source.parent/('season%02d-poster.png'%season),source.parent/('season%02d.png'%season),source.parent.parent/'cover.jpg',source.parent.parent/'poster.png'])
 return artwork
COVER_MAX_BYTES=5*1024*1024
def find_cover(source,listing=None,media_root=None):
 """First existing local artwork for a media file: (path, mtime_ns) or (None, None).
 listing(directory) may return a cached set of names to avoid one stat per candidate."""
 base=media_root or MEDIA.resolve()
 for candidate in cover_candidates(source):
  try:
   if listing is not None and candidate.name not in listing(candidate.parent):continue
   if candidate.is_symlink() or not candidate.is_file():continue
   resolved=candidate.resolve(strict=True)
   info=resolved.stat()
   if base not in resolved.parents or info.st_size>COVER_MAX_BYTES:continue
   return resolved,info.st_mtime_ns
  except OSError:continue
 return None,None
def _sidecar_signature(source):
 # Newest mtime of the NFO files import_local_nfo may read; detects NFOs added later.
 newest=0
 for candidate in (source.with_suffix('.nfo'),source.parent/'movie.nfo'):
  try:
   if not candidate.is_symlink():newest=max(newest,candidate.stat().st_mtime_ns)
  except OSError:pass
 return newest
def _index_file(c,path,library_id,media_root,seen,next_signatures,stats,note,listing,now):
 """Index one media file of a library (body of the scan loop)."""

 # Identity from the real path; computed first so a read error keeps the entry.
 ident=hashlib.sha256(os.path.realpath(str(path)).encode()).hexdigest()[:24]
 stats['checked']+=1
 if stats['checked']%200==0:_scan_update(**stats)
 try:
  resolved=path.resolve(strict=True)
  if media_root not in resolved.parents:return
  seen.add(ident)
  info=resolved.stat()
  size=info.st_size
  signature=(size,info.st_mtime_ns)
  next_signatures[ident]=signature
  row=c.execute('SELECT bytes,mtime_ns,sidecar_ns,cover_path,cover_ns,library_id FROM media WHERE id=?',(ident,)).fetchone()
  sidecar=_sidecar_signature(resolved)
  cover_path,cover_ns=find_cover(resolved,listing,media_root)
  cover_path=str(cover_path) if cover_path else None
  if row is not None and (row[3],row[4],row[5])!=(cover_path,cover_ns,library_id):
   c.execute('UPDATE media SET cover_path=?,cover_ns=?,library_id=? WHERE id=?',(cover_path,cover_ns,library_id,ident))
  if row is not None and row[0]==size and row[1] in (None,info.st_mtime_ns):
   # Unchanged: no header read, no rewrite. Only a new/changed NFO is imported.
   if row[1] is None or row[2]!=sidecar:
    if row[2]!=sidecar:import_local_nfo(c,ident,resolved)
    c.execute('UPDATE media SET mtime_ns=?,sidecar_ns=? WHERE id=?',(info.st_mtime_ns,sidecar,ident))
   stats['indexed']+=1
   return
  recently_written=now-max(info.st_mtime,info.st_ctime)<STABLE_SECONDS
  if recently_written and pending_media_signatures.get(ident)!=signature:
   # Still being copied or just finished: wait. An existing entry stays visible meanwhile.
   stats['deferred']+=1
   if row is not None:stats['indexed']+=1
   return
  kind='video' if path.suffix.lower() in VIDEO else 'audio'
  w,h=probe(resolved) if kind=='video' else (None,None)
  c.execute('INSERT OR REPLACE INTO media(id,path,title,kind,bytes,width,height,mtime_ns,sidecar_ns,cover_path,cover_ns,library_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
   (ident,str(resolved),path.stem,kind,size,w,h,info.st_mtime_ns,sidecar,cover_path,cover_ns,library_id))
  import_local_nfo(c,ident,resolved)
  stats['new' if row is None else 'updated']+=1;stats['indexed']+=1
 except (OSError,ValueError) as exc:
  seen.add(ident)
  note('Datei nicht lesbar: '+str(path.relative_to(MEDIA))+' ('+type(exc).__name__+')')
def scan(trigger='manual',allow_mass_removal=False):
 """Index media below MEDIA. Media files are only read, never changed.

 Index entries are only removed when the walk was complete and plausible: not after read
 errors, not when no media was found at all, and not for a mass removal (more than half of
 the library, at least MASS_REMOVAL_MIN entries) unless an admin confirmed it."""
 started=time.time()
 _scan_update(state='running',trigger=trigger,started=int(started),finished=None,duration=None,checked=0,indexed=0,new=0,
  updated=0,deferred=0,removed=0,removal_blocked=0,errors=[],warning='',result=None)
 stats={'checked':0,'indexed':0,'new':0,'updated':0,'deferred':0,'removed':0,'removal_blocked':0}
 errors=[];warning=''
 def note(message):
  if len(errors)<20:errors.append(message[:240])
 def finish(result):
  _scan_update(state='idle',finished=int(time.time()),duration=round(time.time()-started,1),errors=errors,warning=warning,result=result,**stats)
 if not MEDIA.is_dir():
  warning='Medienordner nicht erreichbar ('+str(MEDIA)+'). Bibliothek unverändert gelassen.'
  finish('warning');return 0
 media_root=MEDIA.resolve()
 seen=set()
 next_signatures={}
 walk_errors=[]
 now=time.time()
 directory_names={}
 def listing(directory):
  key=str(directory)
  if key not in directory_names:
   try:directory_names[key]=set(os.listdir(key))
   except OSError:directory_names[key]=set()
  return directory_names[key]
 with sqlite_session(DATA/'library.sqlite') as c:
  libraries=library_rows(c,enabled_only=True)
  # Every folder of every active library; overlaps are rejected when libraries are saved,
  # so each file belongs to exactly one library.
  walks=[]
  for library in libraries:
   for folder in library['folders']:
    top=MEDIA/folder if folder else MEDIA
    if folder and (top.is_symlink() or not top.is_dir()):
     # A library folder that vanished counts as a read error: nothing is removed.
     walk_errors.append(OSError(2,'Bibliotheksordner fehlt',str(top)));continue
    walks.append((library,top,folder))
  # Ordner, die einer anderen (genaueren) Bibliothek gehören, überspringt die äußere Bibliothek.
  all_folders=[(f,l['id']) for l in libraries for f in l['folders']]
  last_commit=time.monotonic()
  for library,top,folder in walks:
   extensions=category_extensions(library['category'])
   inner={str(MEDIA/f) for f,i in all_folders if i!=library['id'] and f!=folder and (folder=='' or f.startswith(folder+'/'))}
   for base,dirs,files in os.walk(str(top),onerror=walk_errors.append):
    dirs[:]=[d for d in dirs if not d.startswith('.') and not (Path(base)/d).is_symlink() and str(Path(base)/d) not in inner]
    for name in files:
     path=Path(base)/name
     if path.suffix.lower() not in extensions or path.is_symlink():continue
     _index_file(c,path,library['id'],media_root,seen,next_signatures,stats,note,listing,now)
     # Commit at least every second: a scan must not hold the database write lock for its
     # whole duration (playback progress, metadata and library edits would time out).
     if c.in_transaction and time.monotonic()-last_commit>=1.0:
      c.commit()
      # Yield briefly: SQLite's busy handler polls in intervals of up to 100 ms, so without a
      # pause the scan would re-take the lock before a waiting writer gets a chance.
      time.sleep(0.1)
      last_commit=time.monotonic()
  for exc in walk_errors[:5]:note('Ordner nicht lesbar: '+str(getattr(exc,'filename','') or exc))
  # Rows of index entries without an existing library (e.g. left over) are not visible; drop them.
  c.execute('DELETE FROM media WHERE library_id IS NULL OR library_id NOT IN (SELECT id FROM libraries)')
  # Only entries of the libraries scanned now may be missing; disabled libraries stay untouched.
  scanned_ids=[library['id'] for library in libraries]
  marks=','.join('?'*len(scanned_ids)) or 'NULL'
  missing=[ident for (ident,) in c.execute('SELECT id FROM media WHERE library_id IN ('+marks+')',scanned_ids).fetchall() if ident not in seen]
  total=c.execute('SELECT COUNT(*) FROM media WHERE library_id IN ('+marks+')',scanned_ids).fetchone()[0]
  if not libraries:
   warning='Keine aktive Bibliothek. Lege unter Dashboard › Bibliotheken eine Bibliothek an.'
  if missing:
   if walk_errors:
    warning='Einige Ordner waren nicht lesbar. '+str(len(missing))+' fehlende Einträge wurden vorsichtshalber nicht entfernt.'
   elif len(missing)>=MASS_REMOVAL_MIN and len(missing)*2>total and not allow_mass_removal and not seen:
    warning='Keine Mediendateien gefunden. Ist die Freigabe eingehängt? Die Bibliothek ('+str(total)+' Einträge) wurde unverändert gelassen.'
   elif len(missing)>=MASS_REMOVAL_MIN and len(missing)*2>total and not allow_mass_removal:
    warning=str(len(missing))+' von '+str(total)+' Einträgen werden nicht mehr gefunden. Zum Schutz wurde nichts entfernt. Wenn die Dateien wirklich gelöscht wurden, die Bereinigung bestätigen.'
   if warning:
    stats['removal_blocked']=len(missing)
   else:
    # Only index rows are removed; personal metadata and progress stay for returning files.
    for ident in missing:c.execute('DELETE FROM media WHERE id=?',(ident,))
    c.execute('DELETE FROM media_stream_cache WHERE media_id NOT IN (SELECT id FROM media)')
    stats['removed']=len(missing)
 pending_media_signatures.clear()
 pending_media_signatures.update(next_signatures)
 finish('warning' if warning or errors else 'ok')
 return stats['indexed']
scan_pending=threading.Event()
def run_scan(trigger,allow_mass_removal=False,lock_held=False):
 """Run one scan under scan_lock and record failures in the scan status."""
 if not lock_held and not scan_lock.acquire(blocking=False):return None
 try:return scan(trigger,allow_mass_removal)
 except Exception as exc:
  _scan_update(state='idle',finished=int(time.time()),result='error',warning='Scan fehlgeschlagen: '+type(exc).__name__+' '+str(exc)[:160])
  print('Library scan failed:',type(exc).__name__,str(exc)[:160],flush=True)
  return None
 finally:
  scan_lock.release()
  # A library was changed while this scan ran: scan again so the change is picked up.
  if scan_pending.is_set():
   scan_pending.clear();request_scan('library')
def request_scan(trigger='library'):
 """Start a background scan now, or right after the scan that is currently running."""
 if scan_lock.acquire(blocking=False):
  _scan_update(state='running',trigger=trigger)
  threading.Thread(target=run_scan,args=(trigger,False,True),daemon=True).start()
  return True
 scan_pending.set()
 return False
LIBRARY_ERRORS={'INVALID_NAME':'Name: 1–60 Zeichen.','NAME_EXISTS':'Eine Bibliothek mit diesem Namen gibt es schon.',
 'INVALID_CATEGORY':'Unbekannte Kategorie.','INVALID_ENABLED':'Ungültiger Status.','INVALID_FOLDERS':'Bitte 1 bis 20 Ordner auswählen.',
 'INVALID_FOLDER':'Ungültiger Ordner (nur Ordner innerhalb des Medienordners, keine versteckten Ordner).',
 'FOLDER_IS_SYMLINK':'Verknüpfte Ordner (Symlinks) sind aus Sicherheitsgründen nicht erlaubt.','FOLDER_NOT_FOUND':'Ordner nicht gefunden.',
 'FOLDERS_OVERLAP':'Die Ordner überschneiden sich (ein Ordner liegt im anderen).','NOT_FOUND':'Bibliothek nicht gefunden.'}
def library_error(code):
 if code.startswith('FOLDER_USED:'):return {'error':'FOLDER_USED','message':'Der Ordner gehört schon zur Bibliothek „'+code.split(':',1)[1]+'“. Jede Datei kann nur in einer Bibliothek sein.'}
 return {'error':code,'message':LIBRARY_ERRORS.get(code,code)}
def device_label(user_agent):
 ua=(user_agent or '')[:300]
 browser='Firefox' if 'Firefox/' in ua else 'Edge' if 'Edg/' in ua else 'Chrome' if 'Chrome/' in ua else 'Safari' if 'Safari/' in ua else 'Browser'
 platform='Android' if 'Android' in ua else 'iPhone/iPad' if ('iPhone' in ua or 'iPad' in ua) else 'Windows' if 'Windows' in ua else 'Mac' if 'Macintosh' in ua else 'Linux' if 'Linux' in ua else 'Gerät'
 return platform+' · '+browser

TRUSTED_PROXIES=('127.0.0.1','::1','::ffff:127.0.0.1')
def client_ip(handler):
 """Echte Adresse des Zuschauers. Kommt die Anfrage über den eigenen HTTPS-Proxy (Apache auf dem NAS,
 für Zugriff von unterwegs), steht sie in X-Forwarded-For (letzter Eintrag = vom Proxy angehängt)."""
 ip=handler.client_address[0]
 if ip in TRUSTED_PROXIES:
  fwd=(handler.headers.get('X-Forwarded-For') or '').split(',')
  last=fwd[-1].strip() if fwd and fwd[-1].strip() else ''
  if last:return last
 return ip
def via_proxy(handler):
 return handler.client_address[0] in TRUSTED_PROXIES and bool((handler.headers.get('X-Forwarded-For') or '').strip())
def host_allowed(host,server_port):
 host=(host or '').strip().lower()
 port=str(server_port)
 if host in ('127.0.0.1:'+port,'localhost:'+port,'[::1]:'+port) or host in EXTRA_HOSTS:return True
 # A literal IP address (e.g. https://192.168.1.20:8097) cannot be used for DNS rebinding,
 # so direct LAN access by IP is allowed when the server listens beyond localhost.
 if BIND in ('127.0.0.1','localhost','::1'):return False
 name,sep,hport=host.rpartition(':')
 if not sep or hport!=port:return False
 name=name[1:-1] if name.startswith('[') and name.endswith(']') else name
 import ipaddress
 try:ipaddress.ip_address(name);return True
 except ValueError:return False
def update_status(check=True):
 """Installed and latest version for the admin page. Never returns the token."""
 installed=updater.installed_version(ROOT)
 result={'installed':installed or VERSION,'server_version':VERSION,'token_configured':bool(updater.load_token(DATA)),
  'installable':False,'job':updater.read_status(DATA)}
 if not result['token_configured']:
  result.update(status='not_configured',message='GitHub-Token fehlt. Trage unten einen Lesetoken ein, dann kannst du Updates direkt von GitHub installieren.')
  return result
 if not check:
  result.update(status='unchecked',message='Noch nicht geprüft.');return result
 try:release=updater.latest_release(updater.load_token(DATA))
 except updater.UpdateError as e:
  result.update(status='check_failed',message=str(e));return result
 result['latest']=release['version']
 newer=bool(updater.parse_version(installed)) and updater.parse_version(release['version'])>updater.parse_version(installed)
 if not newer:
  result.update(status='up_to_date',message='Du hast die neueste Version.')
 elif not (release['archive'] and release['checksum']):
  result.update(status='no_package',message='Version %s ist auf GitHub, aber ohne Update-Paket.'%release['version'])
 else:
  result.update(status='update_available',installable=True,size=release['archive']['size'],notes=release['notes'],
   message='Version %s ist verfügbar.'%release['version'])
 return result
class Handler(BaseHTTPRequestHandler):
 timeout=120
 def _host_allowed(self):
  return host_allowed(self.headers.get('Host',''),self.server.server_port)
 def _request_allowed(self):
  if self._host_allowed():return True
  self.send(403,'{"error":"INVALID_HOST_LOCAL_ONLY"}')
  return False
 def log_message(self,fmt,*args):pass
 def send(self,status,body,typ='application/json',extra=None):
  # Secure defaults; extra headers replace a default instead of adding a second, conflicting one
  # (a duplicate "Cache-Control: no-store" used to override every cache header).
  headers={'Content-Type':typ,'X-Content-Type-Options':'nosniff','Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY'}
  headers.update(extra or {})
  self.send_response(status)
  for k,v in headers.items():self.send_header(k,v)
  encoded=body if isinstance(body,bytes) else body.encode()
  self.send_header('Content-Length',str(len(encoded)))
  self.end_headers();self.wfile.write(encoded)
 def authorized(self):
  bearer=self.headers.get('Authorization','')
  if not bearer.startswith('Bearer '):return False
  return bool(accounts.user(bearer[7:]))
 def payload(self):
  try:
   length=int(self.headers.get('Content-Length','0'))
   if length<1 or length>4096:return None
   data=json.loads(self.rfile.read(length))
   return data if isinstance(data,dict) else None
  except (ValueError,UnicodeDecodeError):return None
 def do_GET(self):
  if not self._request_allowed():return
  if jf_api.handle(self,'GET'):return
  u=urllib.parse.urlsplit(self.path);p=u.path
  if p=='/health':return self.send(200,json.dumps({'status':'ok','name':'Butchies Media Center','version':VERSION,'tls':bool(TLS_CERT and TLS_KEY)}))
  # WD-Dashboard-Knopf "Konfigurieren" öffnet <NAS>:8097/butchiesmediacenter/index.html -> zur Startseite
  if p=='/butchiesmediacenter' or p.startswith('/butchiesmediacenter/'):return self.send(302,b'','text/plain; charset=utf-8',{'Location':'/'})
  if p=='/api/pair/qr':
   # The QR carries a short-lived pairing code. No remote QR service is contacted.
   if not self.authorized():return self.send(401,'{"error":"AUTH_REQUIRED"}')
   code=urllib.parse.parse_qs(u.query).get('code',[''])[0]
   if not re.fullmatch(r'[A-Za-z0-9_-]{6,128}',code):return self.send(400,'{"error":"INVALID_CODE"}')
   user=accounts.user(self.headers.get('Authorization','')[7:])
   if not user or not accounts.pair_code_valid_for_user(code,user[0]):
    return self.send(404,'{"error":"PAIR_CODE_NOT_APPROVED_OR_EXPIRED"}')
   try:from qr_local import svg_for_text
   except ImportError:return self.send(503,'{"error":"QR_UNAVAILABLE","message":"Python-Paket qrcode fehlt auf diesem Gerät. Kopplungscode manuell eingeben."}')
   # The QR opens this media center directly with the code pre-filled (Host was validated above).
   link=('https' if TLS_CERT and TLS_KEY else 'http')+'://'+self.headers.get('Host','').strip()+'/?pair='+code
   return self.send(200,svg_for_text(link),'image/svg+xml',{'Content-Security-Policy':"default-src 'none'; sandbox",'Cache-Control':'no-store'})
  if p=='/api/libraries':
   user=accounts.user(self.headers.get('Authorization','')[7:]) if self.authorized() else None
   if not user:return self.send(401,'{"error":"AUTH_REQUIRED"}')
   with sqlite_session(DATA/'library.sqlite') as c:
    libraries=library_rows(c)
    counts=dict(c.execute('SELECT library_id,COUNT(*) FROM media GROUP BY library_id').fetchall())
   for library in libraries:
    library['count']=counts.get(library['id'],0);library['category_label']=LIBRARY_CATEGORIES[library['category']]
    # Folder paths only for admins; other users see names and categories.
    if user[2]!='admin':library.pop('folders',None)
   if user[2]!='admin':libraries=[x for x in libraries if x['enabled']]
   return self.send(200,json.dumps({'libraries':libraries,'categories':LIBRARY_CATEGORIES},ensure_ascii=False))
  if p=='/api/libraries/browse':
   # Admin-only listing of sub folders below MEDIA for the folder picker (names only, read-only).
   user=accounts.user(self.headers.get('Authorization','')[7:]) if self.authorized() else None
   if not user:return self.send(401,'{"error":"AUTH_REQUIRED"}')
   if user[2]!='admin':return self.send(403,'{"error":"ADMIN_REQUIRED"}')
   try:folder=normalize_library_folder(urllib.parse.parse_qs(u.query).get('path',[''])[0])
   except ValueError as e:return self.send(400,json.dumps(library_error(str(e)),ensure_ascii=False))
   with sqlite_session(DATA/'library.sqlite') as c:owners=[(f,l['name'],l['id']) for l in library_rows(c) for f in l['folders']]
   base=MEDIA/folder if folder else MEDIA
   entries=[]
   try:
    for entry in sorted(os.scandir(str(base)),key=lambda e:e.name.lower()):
     if entry.name.startswith('.') or entry.is_symlink() or not entry.is_dir(follow_symlinks=False):continue
     rel=(folder+'/' if folder else '')+entry.name
     owner=next(({'id':i,'name':n,'exact':f==rel} for f,n,i in owners if folders_overlap(f,rel)),None)
     entries.append({'name':entry.name,'path':rel,'library':owner})
     if len(entries)>=500:break
   except OSError:return self.send(404,json.dumps(library_error('FOLDER_NOT_FOUND'),ensure_ascii=False))
   owner=next(({'id':i,'name':n,'exact':f==folder} for f,n,i in owners if folders_overlap(f,folder)),None)
   parent=folder.rsplit('/',1)[0] if '/' in folder else ('' if folder else None)
   return self.send(200,json.dumps({'path':folder,'parent':parent,'library':owner,'folders':entries,'truncated':len(entries)>=500},ensure_ascii=False))
  if p=='/api/library/scan-status':
   user=accounts.user(self.headers.get('Authorization','')[7:]) if self.authorized() else None
   if not user:return self.send(401,'{"error":"AUTH_REQUIRED"}')
   with sqlite_session(DATA/'library.sqlite') as c:total=c.execute('SELECT COUNT(*) FROM media').fetchone()[0]
   status=scan_status_snapshot(include_errors=user[2]=='admin');status['library_count']=total
   return self.send(200,json.dumps(status,ensure_ascii=False))
  if p=='/api/library/overview':
   if not self.authorized():return self.send(401,'{"error":"AUTH_REQUIRED"}')
   # Same classification as /api/library, so counts always match what the views show.
   items=library_items()
   groups={'movies':{'count':0,'bytes':0},'series':{'count':0,'bytes':0},'music':{'count':0,'bytes':0}}
   folders={}
   for x in items:
    category={'movie':'movies','series':'series','music':'music'}[x['category']]
    groups[category]['count']+=1;groups[category]['bytes']+=x['bytes'] or 0
    key=(x['folder'],category)
    if key not in folders:folders[key]={'folder':x['folder'],'category':category,'count':0}
    folders[key]['count']+=1
   return self.send(200,json.dumps({'libraries':groups,'folders':sorted(folders.values(),key=lambda x:(x['category'],x['folder'])),'root':str(MEDIA)}))
  streams_match=re.fullmatch(r'/api/media/streams/([0-9a-f]{24})',p)
  if streams_match:
   if not self.authorized():return self.send(401,'{"error":"AUTH_REQUIRED"}')
   ident=streams_match.group(1)
   with sqlite_session(DATA/'library.sqlite') as c:row=c.execute('SELECT path FROM media WHERE id=? AND library_id IN (SELECT id FROM libraries WHERE enabled=1)',(ident,)).fetchone()
   if not row:return self.send(404,'{"error":"NOT_FOUND"}')
   try:
    source=Path(row[0]).resolve(strict=True)
    if MEDIA.resolve() not in source.parents or not source.is_file():return self.send(403,'{"error":"FORBIDDEN"}')
    stat_info=source.stat()
    with sqlite_session(DATA/'library.sqlite') as c:cached=c.execute('SELECT size,mtime_ns,payload FROM media_stream_cache WHERE media_id=?',(ident,)).fetchone()
    if cached and cached[0]==stat_info.st_size and cached[1]==stat_info.st_mtime_ns:
     return self.send(200,cached[2])
    import shutil,subprocess
    binary=ROOT/'bin'/'ffprobe'
    if not binary.is_file():
     located=shutil.which('ffprobe')
     if not located:return self.send(200,json.dumps({'available':False,'reason':'FFPROBE_NOT_INSTALLED','streams':[]}))
     binary=Path(located)
    result=subprocess.run([str(binary),'-v','error','-show_entries','stream=index,codec_type,codec_name,channels,channel_layout,sample_rate:stream_tags=language,title','-of','json',str(source)],capture_output=True,timeout=15)
    if result.returncode!=0:return self.send(200,json.dumps({'available':False,'reason':'PROBE_FAILED','streams':[]}))
    info=json.loads(result.stdout.decode('utf-8'))
    streams=[]
    for entry in info.get('streams',[])[:40]:
     if entry.get('codec_type') not in ('audio','subtitle'):continue
     tags=entry.get('tags') or {}
     streams.append({'index':entry.get('index'),'type':entry.get('codec_type'),'codec':entry.get('codec_name'),'language':tags.get('language','und'),'title':str(tags.get('title',''))[:120],'channels':entry.get('channels'),'layout':entry.get('channel_layout')})
    payload=json.dumps({'available':True,'streams':streams})
    if source.stat().st_size==stat_info.st_size and source.stat().st_mtime_ns==stat_info.st_mtime_ns:
     with sqlite_session(DATA/'library.sqlite') as c:c.execute('INSERT OR REPLACE INTO media_stream_cache(media_id,size,mtime_ns,payload) VALUES(?,?,?,?)',(ident,stat_info.st_size,stat_info.st_mtime_ns,payload))
    return self.send(200,payload)
   except (OSError,ValueError,subprocess.TimeoutExpired,json.JSONDecodeError,sqlite3.Error):return self.send(200,json.dumps({'available':False,'reason':'PROBE_FAILED','streams':[]}))
  subtitle_match=re.fullmatch(r'/api/media/subtitles/([0-9a-f]{24})',p)
  if subtitle_match:
   if not self.authorized():return self.send(401,'{"error":"AUTH_REQUIRED"}')
   with sqlite_session(DATA/'library.sqlite') as c:row=c.execute('SELECT path,kind FROM media WHERE id=? AND library_id IN (SELECT id FROM libraries WHERE enabled=1)',(subtitle_match.group(1),)).fetchone()
   if not row or row[1]!='video':return self.send(404,'{"error":"NOT_FOUND"}')
   try:
    source=Path(row[0]).resolve(strict=True)
    if MEDIA.resolve() not in source.parents or not source.is_file():return self.send(403,'{"error":"FORBIDDEN"}')
    tracks=[]
    for candidate in sorted(source.parent.iterdir()):
     if candidate.suffix.lower() not in ('.srt','.vtt') or not (candidate.stem==source.stem or candidate.stem.startswith(source.stem+'.')):continue
     if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size>1024*1024:continue
     if MEDIA.resolve() not in candidate.resolve(strict=True).parents:continue
     raw=candidate.read_text(encoding='utf-8-sig',errors='replace')
     if candidate.suffix.lower()=='.srt':
      raw=raw.replace('\r\n','\n').replace('\r','\n')
      raw=re.sub(r'(?<=\d),(?=\d{3}(?:\s|$))','.',raw)
      raw=re.sub(r'(?m)^\d+\s*\n(?=\d\d:\d\d:\d\d[.])','',raw)
      raw='WEBVTT\n\n'+raw
     elif not raw.lstrip().startswith('WEBVTT'):continue
     lang=candidate.stem[len(source.stem):].lstrip('.') or 'Standard'
     tracks.append({'label':lang,'vtt':raw})
     if len(tracks)>=12:break
    return self.send(200,json.dumps({'tracks':tracks},ensure_ascii=False))
   except (OSError,ValueError):return self.send(404,'{"error":"SUBTITLES_UNAVAILABLE"}')
  cover_match=re.fullmatch(r'/api/media/cover/([0-9a-f]{24})',p)
  if cover_match:
   if not self.authorized():return self.send(401,'{"error":"AUTH_REQUIRED"}')
   with sqlite_session(DATA/'library.sqlite') as c:row=c.execute('SELECT path,cover_path,cover_ns FROM media WHERE id=? AND library_id IN (SELECT id FROM libraries WHERE enabled=1)',(cover_match.group(1),)).fetchone()
   if not row:return self.send(404,'{"error":"NOT_FOUND"}')
   # Artwork is located during the library scan; a request never searches the disk.
   if not row[1]:return self.send(404,'{"error":"NO_COVER"}')
   try:
    base=MEDIA.resolve()
    if base not in Path(row[0]).resolve(strict=True).parents:return self.send(403,'{"error":"FORBIDDEN"}')
    stored=row[1:]
    cover=Path(stored[0])
    if cover.is_symlink():return self.send(404,'{"error":"NO_COVER"}')
    resolved=cover.resolve(strict=True)
    if base not in resolved.parents or resolved.stat().st_size>COVER_MAX_BYTES:return self.send(404,'{"error":"NO_COVER"}')
    mime='image/png' if resolved.suffix.lower()=='.png' else 'image/jpeg'
    version=str(stored[1] or 0)
    # The URL carries the cover version (?v=), so the browser may keep it; a new cover gets a new URL.
    cache='private, max-age=31536000, immutable' if urllib.parse.parse_qs(u.query).get('v',[''])[0]==version else 'private, no-cache'
    return self.send(200,resolved.read_bytes(),mime,{'Cache-Control':cache,'ETag':'"'+version+'"','X-Content-Type-Options':'nosniff'})
   except OSError:pass
   return self.send(404,'{"error":"NO_LOCAL_COVER"}')
  if p=='/api/playback/progress':
   user=accounts.user(self.headers.get('Authorization','')[7:])
   if not user:return self.send(401,'{"error":"AUTH_REQUIRED"}')
   with sqlite_session(DATA/'library.sqlite') as c:
    rows=c.execute('SELECT p.media_id,p.position,p.duration,p.updated,p.completed FROM playback_progress p JOIN media m ON m.id=p.media_id WHERE p.user_id=? ORDER BY p.updated DESC LIMIT 500',(user[0],)).fetchall()
   return self.send(200,json.dumps({'items':[{'id':row[0],'time':row[1],'duration':row[2],'updated':row[3]*1000,'completed':bool(row[4])} for row in rows]}))
  if p=='/api/account/devices':
   auth=self.headers.get('Authorization','')[7:]
   user=accounts.user(auth)
   if not user:return self.send(401,'{"error":"AUTH_REQUIRED"}')
   return self.send(200,json.dumps({'devices':accounts.list_sessions(user[0],auth)}))
  if p in ('/api/me','/api/users'):
   user=accounts.user(self.headers.get('Authorization','')[7:]) if self.authorized() else None
   if not user:return self.send(401,'{"error":"AUTH_REQUIRED"}')
   if p=='/api/me':return self.send(200,json.dumps({'id':user[0],'name':user[1],'role':user[2]}))
   if user[2]!='admin':return self.send(403,'{"error":"ADMIN_REQUIRED"}')
   return self.send(200,json.dumps(accounts.list_users()))
  if p=='/api/account/status':return self.send(200,json.dumps({'setup_required':accounts.count()==0,'setup_method':'web_code' if setup_code_hash else 'local_cli'}))
  if p=='/api/admin/update/status':
   # Admin-only. Reads the latest GitHub release; installing is a separate POST.
   user=accounts.user(self.headers.get('Authorization','')[7:]) if self.authorized() else None
   if not user:return self.send(401,'{"error":"AUTH_REQUIRED"}')
   if user[2]!='admin':return self.send(403,'{"error":"ADMIN_REQUIRED"}')
   return self.send(200,json.dumps(update_status(urllib.parse.parse_qs(u.query).get('check',['1'])[0]!='0')))

  stream_match=re.fullmatch(r'/api/stream/([a-f0-9]{24})',p)
  ticket=urllib.parse.parse_qs(u.query).get('ticket',[''])[0] if stream_match else ''
  ticket_ok=False
  if stream_match and ticket:
   with playback_lock:entry=playback_tickets.get(hashlib.sha256(ticket.encode()).hexdigest())
   ticket_ok=bool(entry and entry[0]==stream_match.group(1) and entry[1]>time.time() and accounts.session_hash_valid(entry[2]))
  if not (p=='/api/library' or stream_match):return self.send(404,'{"error":"NOT_FOUND"}')
  if not self.authorized() and not ticket_ok:return self.send(401,'{"error":"AUTH_REQUIRED"}')
  if p=='/api/library':return self.send(200,json.dumps(library_items()))
  m=stream_match
  if m:
   with sqlite_session(DATA/'library.sqlite') as c:r=c.execute('SELECT path,kind,width,height FROM media WHERE id=? AND library_id IN (SELECT id FROM libraries WHERE enabled=1)',(m.group(1),)).fetchone()
   if not r:return self.send(404,'{"error":"NOT_FOUND"}')
   path,kind,w,h=r
   # Refuse if media was replaced after indexing; no stale metadata bypass.
   if kind=='video' and probe(Path(path))!=(w,h):return self.send(403,'{"error":"RESCAN_REQUIRED"}')
   if kind=='video' and (not w or not h or w>1920 or h>1080):return self.send(403,json.dumps({'error':'UNSUPPORTED_4K_NAS','message':'Video kann nicht abgespielt werden: maximal Full HD (1920x1080). Bei unbekannter Auflösung ist Wiedergabe ebenfalls gesperrt.','width':w,'height':h}))
   f=Path(path)
   try:
    if MEDIA.resolve() not in f.resolve(strict=True).parents:return self.send(403,'{"error":"FORBIDDEN"}')
    before=f.stat();size=before.st_size;start=0;end=size-1;rangehead=self.headers.get('Range','')
    if rangehead:
     mt=re.fullmatch(r'bytes=(\d*)-(\d*)',rangehead)
     if not mt:return self.send(416,'{"error":"INVALID_RANGE"}',extra={'Content-Range':'bytes */'+str(size)})
     a,b=mt.groups()
     if not a and not b:return self.send(416,'{"error":"INVALID_RANGE"}',extra={'Content-Range':'bytes */'+str(size)})
     if not a:
      if int(b)==0:return self.send(416,'{"error":"INVALID_RANGE"}',extra={'Content-Range':'bytes */'+str(size)})
      start=max(0,size-int(b))
     else:start=int(a)
     if b and a:end=min(end,int(b))
     if start>=size or end<start:return self.send(416,'{"error":"INVALID_RANGE"}',extra={'Content-Range':'bytes */'+str(size)})
    if size==0:return self.send(416,'{"error":"EMPTY_MEDIA"}',extra={'Content-Range':'bytes */0'})
    flags=os.O_RDONLY | getattr(os,'O_NOFOLLOW',0)
    fd=os.open(str(f),flags)
    # The file may have changed between stat and open; refuse stale ranges.
    st=os.fstat(fd)
    # Verify the opened file itself, not just a path that can be swapped.
    if not stat.S_ISREG(st.st_mode) or st.st_size!=size or (st.st_dev,st.st_ino)!=(before.st_dev,before.st_ino):
     os.close(fd)
     return self.send(409,'{"error":"MEDIA_CHANGED_RESCAN_REQUIRED"}')
    length=end-start+1
    try:
     self.send_response(206 if rangehead else 200)
     self.send_header('Content-Type',MIME.get(f.suffix.lower(),mimetypes.guess_type(f.name)[0] or 'application/octet-stream'))
     self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(length))
     if rangehead:self.send_header('Content-Range','bytes %d-%d/%d'%(start,end,size))
     self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.end_headers()
     with os.fdopen(fd,'rb') as stream:
      fd=-1
      stream.seek(start)
      while length>0:
       buf=stream.read(min(65536,length))
       if not buf:break
       self.wfile.write(buf);length-=len(buf)
    finally:
     if fd>=0:os.close(fd)
   except (OSError,BrokenPipeError,ConnectionResetError):pass
   return
  self.send(404,'{"error":"NOT_FOUND"}')
 def do_HEAD(self):
  if not self._request_allowed():return
  if jf_api.handle(self,'HEAD'):return
  self.send(404,'{"error":"NOT_FOUND"}')
 def do_DELETE(self):
  if not self._request_allowed():return
  if jf_api.handle(self,'DELETE'):return
  self.send(404,'{"error":"NOT_FOUND"}')
 def do_POST(self):
  if not self._request_allowed():return
  if jf_api.handle(self,'POST'):return
  p=urllib.parse.urlsplit(self.path).path
  if p in ('/api/admin/update/token','/api/admin/update/install'):
   user=accounts.user(self.headers.get('Authorization','')[7:]) if self.authorized() else None
   if not user:return self.send(401,'{"error":"AUTH_REQUIRED"}')
   if user[2]!='admin':return self.send(403,'{"error":"ADMIN_REQUIRED"}')
   data=self.payload() or {}
   if p=='/api/admin/update/token':
    try:configured=updater.save_token(DATA,str(data.get('token',''))[:300])
    except updater.UpdateError as e:return self.send(400,json.dumps({'error':'INVALID_TOKEN','message':str(e)}))
    return self.send(200,json.dumps({'token_configured':configured}))
   version=str(data.get('version',''))[:20]
   if not updater.parse_version(version):return self.send(400,'{"error":"VERSION_REQUIRED"}')
   if not updater.load_token(DATA):return self.send(400,json.dumps({'error':'TOKEN_REQUIRED','message':'Kein GitHub-Token eingerichtet.'}))
   if not updater.start(DATA,ROOT,version):return self.send(409,json.dumps({'error':'UPDATE_RUNNING','message':'Ein Update läuft bereits.'}))
   return self.send(202,json.dumps({'job':updater.read_status(DATA)}))
  if p=='/api/account/setup':
   client=client_ip(self);now=time.monotonic()
   with login_lock:
    hits=[t for t in login_attempts.get('setup:'+client,[]) if now-t<300]
    if len(hits)>=10:return self.send(429,'{"error":"RATE_LIMITED"}',extra={'Retry-After':'300'})
    hits.append(now);login_attempts['setup:'+client]=hits
   data=self.payload() or {}
   code=str(data.get('code','')).strip().upper().replace('-','').replace(' ','')[:32]
   name=str(data.get('username',''))[:64];password=str(data.get('password',''))[:256]
   with setup_lock:
    if accounts.count():return self.send(403,'{"error":"SETUP_COMPLETE"}')
    if not setup_code_hash:return self.send(403,'{"error":"USE_LOCAL_CLI_SETUP"}')
    if not hmac.compare_digest(hashlib.sha256(code.encode()).hexdigest(),setup_code_hash):
     return self.send(403,json.dumps({'error':'INVALID_SETUP_CODE','message':'Einrichtungscode falsch. Er steht in der Datei Butchies_Media_Center_Einrichtungscode.txt in der Public-Freigabe.'}))
    try:accounts.register_first_admin(name,password)
    except ValueError as e:
     return self.send(400,json.dumps({'error':str(e),'message':'Benutzername 3-32 Zeichen (Buchstaben, Ziffern, _ oder -), Passwort mindestens 6 Zeichen.'}))
    clear_setup_code()
   token=accounts.login(name,password)
   return self.send(200,json.dumps({'token':token,'expires_in':3600}))
  if p=='/api/account/login':
   data=self.payload() or {}
   name=str(data.get('username',''))[:64];password=str(data.get('password',''))[:256]
   client=client_ip(self)
   now=time.monotonic()
   with login_lock:
    if len(login_attempts)>512:
     for key,attempts in list(login_attempts.items()):
      if not attempts or now-attempts[-1]>=300:login_attempts.pop(key,None)
    hits=[t for t in login_attempts.get(client,[]) if now-t<300]
    login_attempts[client]=hits
    if len(hits)>=10:return self.send(429,'{"error":"RATE_LIMITED"}',extra={'Retry-After':'300'})
    hits.append(now)
   remember=data.get('remember') is True
   token=accounts.login(name,password,remember,device_label(self.headers.get('User-Agent','')))
   if token:
    with login_lock:login_attempts.pop(client,None)
   return self.send(200,json.dumps({'token':token,'expires_in':2592000 if remember else 3600})) if token else self.send(401,'{"error":"INVALID_LOGIN"}')
  if p=='/api/pair/start':
   if not self.authorized():return self.send(401,'{"error":"AUTH_REQUIRED"}')
   return self.send(200,json.dumps({'code':accounts.pair_start(),'expires_in':180}))
  if p=='/api/pair/redeem':
   client=client_ip(self);now=time.monotonic()
   with login_lock:
    hits=[t for t in login_attempts.get('pair:'+client,[]) if now-t<300]
    if len(hits)>=10:return self.send(429,'{"error":"RATE_LIMITED"}',extra={'Retry-After':'300'})
    hits.append(now);login_attempts['pair:'+client]=hits
   data=self.payload() or {};code=str(data.get('code',''))
   if len(code)>128:return self.send(400,'{"error":"INVALID_CODE"}')
   token=accounts.pair_redeem(code,device_label(self.headers.get('User-Agent','')))
   return self.send(200,json.dumps({'token':token,'expires_in':3600})) if token else self.send(409,'{"error":"PENDING_OR_EXPIRED"}')
  if not self.authorized():return self.send(401,'{"error":"AUTH_REQUIRED"}')
  if p=='/api/pair/approve':
   data=self.payload() or {};auth=self.headers.get('Authorization','')[7:]
   user=accounts.user(auth)
   if not user:return self.send(403,'{"error":"ACCOUNT_REQUIRED"}')
   ok=accounts.pair_approve(str(data.get('code','')),user[0])
   return self.send(200,json.dumps({'approved':ok}))
  if p=='/api/account/devices/revoke':
   user=accounts.user(self.headers.get('Authorization','')[7:])
   if not user:return self.send(401,'{"error":"AUTH_REQUIRED"}')
   data=self.payload() or {}
   session_id=str(data.get('id',''))
   ok=accounts.revoke_session(user[0],session_id)
   return self.send(200,json.dumps({'revoked':ok})) if ok else self.send(404,'{"error":"SESSION_NOT_FOUND"}')
  if p=='/api/account/logout':
   accounts.logout(self.headers.get('Authorization','')[7:]);return self.send(200,'{"status":"LOGGED_OUT"}')
  m=re.fullmatch(r'/api/playback-ticket/([a-f0-9]{24})',p)
  if m:
   with sqlite_session(DATA/'library.sqlite') as c:
    found=c.execute('SELECT kind,width,height FROM media WHERE id=? AND library_id IN (SELECT id FROM libraries WHERE enabled=1)',(m.group(1),)).fetchone()
   if not found:return self.send(404,'{"error":"NOT_FOUND"}')
   if found[0]=='video' and (not found[1] or not found[2] or found[1]>1920 or found[2]>1080):
    return self.send(403,'{"error":"UNSUPPORTED_4K_NAS"}')
   if found[0]=='video':
    with sqlite_session(DATA/'library.sqlite') as c: current_path=c.execute('SELECT path FROM media WHERE id=?',(m.group(1),)).fetchone()[0]
    if probe(Path(current_path))!=(found[1],found[2]):return self.send(403,'{"error":"RESCAN_REQUIRED"}')
   now=time.time()
   ticket=secrets.token_urlsafe(32)
   with playback_lock:
    for k,v in list(playback_tickets.items()):
     if v[1]<=now:playback_tickets.pop(k,None)
    playback_tickets[hashlib.sha256(ticket.encode()).hexdigest()]=(m.group(1),now+600,hashlib.sha256(self.headers.get('Authorization','')[7:].encode()).hexdigest())
   return self.send(200,json.dumps({'url':'/api/stream/'+m.group(1)+'?ticket='+urllib.parse.quote(ticket),'expires_in':600}),extra={'Referrer-Policy':'no-referrer'})
  if p in ('/api/users/add','/api/users/delete','/api/users/password','/api/account/password'):
   auth=self.headers.get('Authorization','')[7:];user=accounts.user(auth)
   if not user:return self.send(401,'{"error":"AUTH_REQUIRED"}')
   data=self.payload() or {}
   messages={'INVALID_CREDENTIALS':'Benutzername 3-32 Zeichen (Buchstaben, Ziffern, _ oder -), Passwort mindestens 6 Zeichen.',
    'USER_EXISTS':'Diesen Benutzernamen gibt es schon.','USER_NOT_FOUND':'Benutzer nicht gefunden.',
    'LAST_ADMIN':'Der letzte Administrator kann nicht gelöscht werden.','INVALID_ROLE':'Ungültige Rolle.','WRONG_PASSWORD':'Aktuelles Passwort falsch.'}
   try:
    if p=='/api/account/password':
     if not accounts.login(user[1],str(data.get('old_password',''))[:256]):raise ValueError('WRONG_PASSWORD')
     accounts.set_password(user[0],str(data.get('password',''))[:256]);return self.send(200,'{"status":"PASSWORD_CHANGED"}')
    if user[2]!='admin':return self.send(403,'{"error":"ADMIN_REQUIRED"}')
    if p=='/api/users/add':
     uid=accounts.add_user(str(data.get('username',''))[:64],str(data.get('password',''))[:256],str(data.get('role','user')))
     return self.send(200,json.dumps({'id':uid}))
    target=data.get('id')
    if not isinstance(target,int):return self.send(400,'{"error":"INVALID_ID"}')
    if p=='/api/users/delete':
     if target==user[0]:return self.send(400,json.dumps({'error':'SELF_DELETE','message':'Du kannst dich nicht selbst löschen.'}))
     accounts.delete_user(target);return self.send(200,'{"status":"DELETED"}')
    accounts.set_password(target,str(data.get('password',''))[:256]);return self.send(200,'{"status":"PASSWORD_CHANGED"}')
   except ValueError as e:
    code=str(e);return self.send(400 if code!='USER_NOT_FOUND' else 404,json.dumps({'error':code,'message':messages.get(code,code)}))
  if p=='/api/playback/progress':
   user=accounts.user(self.headers.get('Authorization','')[7:])
   if not user:return self.send(401,'{"error":"AUTH_REQUIRED"}')
   data=self.payload() or {}
   media_id=data.get('id');position=data.get('time');duration=data.get('duration');finished=data.get('finished') is True
   client_updated=data.get('client_updated')
   if client_updated is not None and (type(client_updated) is not int or client_updated<0 or abs(client_updated-int(time.time()*1000))>300000):return self.send(400,'{"error":"INVALID_TIMESTAMP"}')
   if not isinstance(media_id,str) or not re.fullmatch(r'[0-9a-f]{24}',media_id) or type(position) is not int or type(duration) is not int or not 0<=position<=864000 or not 1<=duration<=864000:return self.send(400,'{"error":"INVALID_PROGRESS"}')
   with sqlite_session(DATA/'library.sqlite') as c:
    # Serialize the read/compare/write operation across concurrent requests.
    c.execute('BEGIN IMMEDIATE')
    if not c.execute("SELECT 1 FROM media WHERE id=? AND kind='video'",(media_id,)).fetchone():return self.send(404,'{"error":"NOT_FOUND"}')
    if client_updated is not None:
     existing=c.execute('SELECT updated FROM playback_progress WHERE user_id=? AND media_id=?',(user[0],media_id)).fetchone()
     if existing and client_updated<existing[0]*1000:return self.send(200,'{"status":"STALE_IGNORED"}')
    if data.get('rewind') is True and 10<=position<duration-20:
     c.execute('INSERT INTO playback_progress(user_id,media_id,position,duration,updated,completed) VALUES(?,?,?,?,?,0) ON CONFLICT(user_id,media_id) DO UPDATE SET position=excluded.position,duration=excluded.duration,updated=excluded.updated WHERE playback_progress.completed=0',(user[0],media_id,position,duration,int(time.time())))
    elif finished or position>=duration-20:
     c.execute('INSERT INTO playback_progress(user_id,media_id,position,duration,updated,completed) VALUES(?,?,?,?,?,1) ON CONFLICT(user_id,media_id) DO UPDATE SET position=excluded.position,duration=excluded.duration,updated=excluded.updated,completed=1',(user[0],media_id,duration,duration,int(time.time())))
    elif position>=10:
     c.execute('INSERT INTO playback_progress(user_id,media_id,position,duration,updated,completed) VALUES(?,?,?,?,?,0) ON CONFLICT(user_id,media_id) DO UPDATE SET position=CASE WHEN playback_progress.completed=1 THEN playback_progress.position ELSE MAX(playback_progress.position,excluded.position) END,duration=CASE WHEN playback_progress.completed=1 THEN playback_progress.duration ELSE excluded.duration END,updated=CASE WHEN playback_progress.completed=1 THEN playback_progress.updated ELSE excluded.updated END,completed=CASE WHEN playback_progress.completed=1 THEN 1 ELSE 0 END',(user[0],media_id,position,duration,int(time.time())))
   return self.send(200,'{"status":"SAVED"}')
  if p=='/api/playback/watched':
   user=accounts.user(self.headers.get('Authorization','')[7:])
   if not user:return self.send(401,'{"error":"AUTH_REQUIRED"}')
   data=self.payload() or {}
   media_id=data.get('id');watched=data.get('watched')
   if not isinstance(media_id,str) or not re.fullmatch(r'[0-9a-f]{24}',media_id) or type(watched) is not bool:return self.send(400,'{"error":"INVALID_WATCHED"}')
   with sqlite_session(DATA/'library.sqlite') as c:
    if not c.execute("SELECT 1 FROM media WHERE id=? AND kind='video'",(media_id,)).fetchone():return self.send(404,'{"error":"NOT_FOUND"}')
    if watched:
     c.execute('INSERT INTO playback_progress(user_id,media_id,position,duration,updated,completed) VALUES(?,?,0,0,?,1) ON CONFLICT(user_id,media_id) DO UPDATE SET position=0,duration=0,updated=excluded.updated,completed=1',(user[0],media_id,int(time.time())))
    else:c.execute('DELETE FROM playback_progress WHERE user_id=? AND media_id=?',(user[0],media_id))
   return self.send(200,'{"status":"SAVED"}')
  if p in ('/api/libraries/save','/api/libraries/delete'):
   user=accounts.user(self.headers.get('Authorization','')[7:])
   if not user or user[2]!='admin':return self.send(403,'{"error":"ADMIN_REQUIRED"}')
   data=self.payload() or {}
   library_id=data.get('id')
   if library_id is not None and (type(library_id) is not int or library_id<1):return self.send(400,json.dumps(library_error('NOT_FOUND'),ensure_ascii=False))
   removed=0
   try:
    with sqlite_session(DATA/'library.sqlite') as c:
     c.execute('BEGIN IMMEDIATE')
     if library_id is not None and not c.execute('SELECT 1 FROM libraries WHERE id=?',(library_id,)).fetchone():raise ValueError('NOT_FOUND')
     now=int(time.time())
     if p=='/api/libraries/delete':
      if library_id is None:raise ValueError('NOT_FOUND')
      # Only the library and its index rows; media files, custom metadata and progress stay.
      removed=c.execute('DELETE FROM media WHERE library_id=?',(library_id,)).rowcount
      c.execute('DELETE FROM library_folders WHERE library_id=?',(library_id,))
      c.execute('DELETE FROM libraries WHERE id=?',(library_id,))
      c.execute('DELETE FROM media_stream_cache WHERE media_id NOT IN (SELECT id FROM media)')
      result={'status':'DELETED','removed_entries':removed}
     else:
      name,category,folders,enabled=validate_library(c,data,library_id)
      if library_id is None:
       position=c.execute('SELECT COALESCE(MAX(position),0)+1 FROM libraries').fetchone()[0]
       c.execute('INSERT INTO libraries(name,category,enabled,position,created,updated) VALUES(?,?,?,?,?,?)',(name,category,int(enabled),position,now,now))
       library_id=c.execute('SELECT last_insert_rowid()').fetchone()[0]
      else:
       c.execute('UPDATE libraries SET name=?,category=?,enabled=?,updated=? WHERE id=?',(name,category,int(enabled),now,library_id))
       c.execute('DELETE FROM library_folders WHERE library_id=?',(library_id,))
      for folder in folders:c.execute('INSERT INTO library_folders(library_id,path) VALUES(?,?)',(library_id,folder))
      # Changing folders or category is an explicit admin action: drop index rows that no
      # longer belong here right away (files are never touched).
      removed=prune_library_index(c,library_id,category,folders)
      c.execute('DELETE FROM media_stream_cache WHERE media_id NOT IN (SELECT id FROM media)')
      result={'status':'SAVED','id':library_id,'removed_entries':removed}
   except ValueError as e:
    return self.send(404 if str(e)=='NOT_FOUND' else 400,json.dumps(library_error(str(e)),ensure_ascii=False))
   result['scan_started']=request_scan('library')
   return self.send(200,json.dumps(result,ensure_ascii=False))
  if p=='/api/library/rescan':
   # Non-blocking: starts a background scan; progress via GET /api/library/scan-status.
   user=accounts.user(self.headers.get('Authorization','')[7:])
   if not user or user[2]!='admin':return self.send(403,'{"error":"ADMIN_REQUIRED"}')
   allow=(self.payload() or {}).get('allow_mass_removal') is True
   if not scan_lock.acquire(blocking=False):return self.send(409,json.dumps({'error':'SCAN_IN_PROGRESS','scan':scan_status_snapshot()},ensure_ascii=False))
   _scan_update(state='running',trigger='manual')
   threading.Thread(target=run_scan,args=('manual',allow,True),daemon=True).start()
   return self.send(202,json.dumps({'status':'STARTED','scan':scan_status_snapshot()},ensure_ascii=False))
  if p=='/api/media/details':
   user=accounts.user(self.headers.get('Authorization','')[7:])
   if not user or user[2]!='admin':return self.send(403,'{"error":"ADMIN_REQUIRED"}')
   data=self.payload() or {}
   media_id=data.get('id')
   if not isinstance(media_id,str) or not re.fullmatch(r'[0-9a-f]{24}',media_id):return self.send(400,'{"error":"INVALID_ID"}')
   title=data.get('title','');description=data.get('description','');year=data.get('year');genre=data.get('genre','');rating=data.get('rating')
   if not isinstance(title,str) or len(title)>180 or not isinstance(description,str) or len(description)>2000:return self.send(400,'{"error":"INVALID_METADATA"}')
   if not isinstance(genre,str) or len(genre)>100:return self.send(400,'{"error":"INVALID_GENRE"}')
   if rating in ('',None):rating=None
   elif type(rating) not in (float,int) or not 0<=rating<=10:return self.send(400,'{"error":"INVALID_RATING"}')
   if year in ('',None):year=None
   elif type(year) is not int or year<1888 or year>2200:return self.send(400,'{"error":"INVALID_YEAR"}')
   with sqlite_session(DATA/'library.sqlite') as c:
    if not c.execute('SELECT 1 FROM media WHERE id=?',(media_id,)).fetchone():return self.send(404,'{"error":"NOT_FOUND"}')
    c.execute('INSERT OR REPLACE INTO media_details(media_id,custom_title,description,year,genre,rating) VALUES(?,?,?,?,?,?)',(media_id,title.strip(),description.strip(),year,genre.strip(),rating))
   return self.send(200,'{"status":"SAVED"}')
  if p=='/api/scan':
   auth=self.headers.get('Authorization','')[7:]
   user=accounts.user(auth)
   if not user or user[2]!='admin':return self.send(403,'{"error":"ADMIN_REQUIRED"}')
   # Legacy synchronous scan (kept for older clients).
   if not scan_lock.acquire(blocking=False):return self.send(409,'{"error":"SCAN_IN_PROGRESS"}')
   count=run_scan('manual',lock_held=True)
   if count is None:return self.send(500,'{"error":"SCAN_FAILED"}')
   return self.send(200,json.dumps({'indexed':count,'scan':scan_status_snapshot()},ensure_ascii=False))
  self.send(404,'{"error":"NOT_FOUND"}')
class MediaServer(ThreadingHTTPServer):
 daemon_threads=True
 tls_context=None
 def finish_request(self,request,client_address):
  # Runs in the per-connection thread. With HTTPS, a plain-HTTP request on the same port (e.g. the
  # WD dashboard's "Konfigurieren" button opens http://<NAS>:8097) gets a redirect to https://
  # instead of a dropped connection. A TLS connection always starts with byte 0x16 (handshake).
  if self.tls_context is None:return super().finish_request(request,client_address)
  request.settimeout(15)
  try:first=request.recv(1,socket.MSG_PEEK)
  except OSError:return
  if not first:return
  # Klartext-HTTP: wie bei Jellyfin direkt bedienen (Jellyfin-Apps auf Handy/TV akzeptieren kein selbst
  # ausgestelltes Zertifikat). Browser nutzen weiter https://. Nur im Heimnetz verwenden.
  if first!=b'\x16':return super().finish_request(request,client_address)
  secure=self.tls_context.wrap_socket(request,server_side=True)
  try:self.RequestHandlerClass(secure,client_address,self)
  finally:
   # Same graceful close as socketserver (shutdown, then close); a plain close() with unread
   # request data would reset the connection before the client read the response.
   self.shutdown_request(secure)
 def handle_error(self,request,client_address):
  # One short line instead of a traceback (e.g. plain HTTP sent to the HTTPS port).
  import sys
  e=sys.exc_info()[1]
  print('Connection error from',client_address[0],type(e).__name__,str(e)[:120],flush=True)
def redirect_plain_http(sock,server_port):
 """Answer one plain-HTTP request with 301 to the same address via https. Only hosts that the
 server itself accepts are used as redirect target; nothing else is read or served."""
 data=b''
 try:
  while b'\r\n\r\n' not in data and len(data)<8192:
   chunk=sock.recv(2048)
   if not chunk:break
   data+=chunk
 except OSError:return
 head=data.split(b'\r\n\r\n',1)[0].decode('latin-1','replace').split('\r\n')
 parts=head[0].split(' ') if head else []
 target=parts[1] if len(parts)==3 and parts[1].startswith('/') else '/'
 if len(target)>2000 or any(ch in target for ch in '\r\n\\') or target.startswith('//'):target='/'
 host=next((line.split(':',1)[1].strip() for line in head[1:] if line.lower().startswith('host:')),'')
 if host_allowed(host,server_port):
  response='HTTP/1.1 301 Moved Permanently\r\nLocation: https://'+host.lower()+target+'\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: 0\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n'
 else:
  response='HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'
 try:sock.sendall(response.encode('latin-1'))
 except OSError:pass
def make_server():
 httpd=MediaServer((BIND,PORT),Handler)
 if TLS_CERT and TLS_KEY:
  import ssl
  ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
  ctx.minimum_version=ssl.TLSVersion.TLSv1_2
  ctx.load_cert_chain(TLS_CERT,TLS_KEY)
  # TLS is set up per connection in its own thread (MediaServer.finish_request), so one slow
  # client cannot block accept() and plain HTTP can be redirected.
  httpd.tls_context=ctx
 return httpd
if __name__=='__main__':
 init()
 accounts=Accounts(DATA/'accounts.sqlite')
 import sys
 jf_api.setup(sys.modules[__name__])
 prepare_setup_code()
 def automatic_scan_loop():
  # Low-resource polling works on ARMv7 NAS without watchdog/inotify packages.
  trigger='startup'
  while True:
   count=run_scan(trigger)
   if count is not None:
    status=scan_status_snapshot()
    print('BMC library scan (%s): %d indexed, %d new, %d updated, %d deferred, %d removed%s'%(trigger,count,status['new'],status['updated'],status['deferred'],status['removed'],' - '+status['warning'] if status['warning'] else ''),flush=True)
   trigger='auto'
   time.sleep(AUTO_SCAN_SECONDS)
 threading.Thread(target=automatic_scan_loop,daemon=True).start()
 httpd=make_server()
 print('Butchies Media Center listening on','https' if TLS_CERT and TLS_KEY else 'http',BIND,PORT,flush=True)
 httpd.serve_forever()
