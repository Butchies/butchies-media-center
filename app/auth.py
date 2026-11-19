"""Local prototype identity service. Do not expose to public internet without TLS/review."""
import sqlite3, hashlib, hmac, secrets, time, re
from pathlib import Path
from contextlib import contextmanager

@contextmanager
def sqlite_session(db_path):
    """Commit on success, roll back on failure, and always close the connection."""
    connection = sqlite3.connect(str(db_path))
    try:
        with connection:
            yield connection
    finally:
        connection.close()


class Accounts:
    def __init__(self, db):
        self.db = str(db)
        with sqlite_session(self.db) as c:
            c.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, salt BLOB NOT NULL, digest BLOB NOT NULL, role TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires INTEGER NOT NULL)')
            cols={row[1] for row in c.execute('PRAGMA table_info(sessions)')}
            if 'device' not in cols:c.execute("ALTER TABLE sessions ADD COLUMN device TEXT NOT NULL DEFAULT 'Unbekanntes Gerät'")
            if 'created' not in cols:c.execute("ALTER TABLE sessions ADD COLUMN created INTEGER NOT NULL DEFAULT 0")
            c.execute('CREATE TABLE IF NOT EXISTS pairing (code_hash TEXT PRIMARY KEY, expires INTEGER NOT NULL, user_id INTEGER, redeemed INTEGER DEFAULT 0)')
    def count(self):
        with sqlite_session(self.db) as c:return c.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    def register_first_admin(self,name,password):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{3,32}',name) or len(password)<6:raise ValueError('INVALID_CREDENTIALS')
        salt=secrets.token_bytes(16);digest=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1)
        with sqlite_session(self.db) as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT COUNT(*) FROM users').fetchone()[0]:raise ValueError('SETUP_COMPLETE')
            c.execute('INSERT INTO users(name,salt,digest,role) VALUES(?,?,?,?)',(name,salt,digest,'admin'))
    @staticmethod
    def _check(name,password):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{3,32}',name or '') or len(password or '')<6:raise ValueError('INVALID_CREDENTIALS')
    @staticmethod
    def _digest(password):
        salt=secrets.token_bytes(16)
        return salt,hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1)
    def list_users(self):
        with sqlite_session(self.db) as c:
            return [{'id':r[0],'name':r[1],'role':r[2]} for r in c.execute('SELECT id,name,role FROM users ORDER BY id')]
    def add_user(self,name,password,role='user'):
        self._check(name,password)
        if role not in ('user','admin'):raise ValueError('INVALID_ROLE')
        salt,digest=self._digest(password)
        try:
            with sqlite_session(self.db) as c:
                c.execute('INSERT INTO users(name,salt,digest,role) VALUES(?,?,?,?)',(name,salt,digest,role))
                return c.execute('SELECT last_insert_rowid()').fetchone()[0]
        except sqlite3.IntegrityError:raise ValueError('USER_EXISTS')
    def set_password(self,user_id,password):
        if len(password or '')<6:raise ValueError('INVALID_CREDENTIALS')
        salt,digest=self._digest(password)
        with sqlite_session(self.db) as c:
            if c.execute('UPDATE users SET salt=?,digest=? WHERE id=?',(salt,digest,user_id)).rowcount!=1:raise ValueError('USER_NOT_FOUND')
            # Changing a password signs the user out everywhere.
            c.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))
    def delete_user(self,user_id):
        with sqlite_session(self.db) as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT role FROM users WHERE id=?',(user_id,)).fetchone()
            if not row:raise ValueError('USER_NOT_FOUND')
            if row[0]=='admin' and c.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]<=1:
                raise ValueError('LAST_ADMIN')
            c.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))
            c.execute('UPDATE pairing SET redeemed=1 WHERE user_id=?',(user_id,))
            c.execute('DELETE FROM users WHERE id=?',(user_id,))
    def login(self,name,password,remember=False,device='Browser'):
        with sqlite_session(self.db) as c:row=c.execute('SELECT id,salt,digest FROM users WHERE name=?',(name,)).fetchone()
        salt=row[1] if row else b'\0'*16
        computed=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1)
        if not row or not hmac.compare_digest(computed,row[2]):return None
        token=secrets.token_urlsafe(32)
        with sqlite_session(self.db) as c:c.execute('INSERT INTO sessions(token_hash,user_id,expires,device,created) VALUES(?,?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),row[0],int(time.time())+(2592000 if remember else 3600),str(device)[:80],int(time.time())))
        return token
    def user(self,token):
        if not token:return None
        with sqlite_session(self.db) as c:
            return c.execute('SELECT users.id,users.name,users.role FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires>?',(hashlib.sha256(token.encode()).hexdigest(),int(time.time()))).fetchone()
    def session_hash_valid(self,token_hash):
        with sqlite_session(self.db) as c:
            return c.execute('SELECT 1 FROM sessions WHERE token_hash=? AND expires>?',(token_hash,int(time.time()))).fetchone() is not None
    def list_sessions(self,user_id,current_token):
        now=int(time.time());current_hash=hashlib.sha256(current_token.encode()).hexdigest()
        with sqlite_session(self.db) as c:
            c.execute('DELETE FROM sessions WHERE expires<=?',(now,))
            rows=c.execute('SELECT token_hash,device,created,expires FROM sessions WHERE user_id=? ORDER BY created DESC',(user_id,)).fetchall()
        return [{'id':r[0],'device':r[1],'created':r[2],'expires':r[3],'current':r[0]==current_hash} for r in rows]
    def revoke_session(self,user_id,session_id):
        if not re.fullmatch(r'[0-9a-f]{64}',session_id or ''):return False
        with sqlite_session(self.db) as c:
            return c.execute('DELETE FROM sessions WHERE user_id=? AND token_hash=?',(user_id,session_id)).rowcount==1
    def logout(self,token):
        with sqlite_session(self.db) as c:c.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
    def pair_start(self):
        code=secrets.token_urlsafe(24)
        with sqlite_session(self.db) as c:c.execute('INSERT INTO pairing(code_hash,expires) VALUES(?,?)',(hashlib.sha256(code.encode()).hexdigest(),int(time.time())+180))
        return code
    def pair_code_valid_for_user(self,code,user_id):
        """Only show a QR for an approved, unredeemed code belonging to this user."""
        with sqlite_session(self.db) as c:
            return c.execute(
                'SELECT 1 FROM pairing WHERE code_hash=? AND expires>? AND user_id=? AND redeemed=0',
                (hashlib.sha256(code.encode()).hexdigest(),int(time.time()),user_id)
            ).fetchone() is not None
    def pair_approve(self,code,user_id):
        with sqlite_session(self.db) as c:
            result=c.execute('UPDATE pairing SET user_id=? WHERE code_hash=? AND expires>? AND user_id IS NULL AND redeemed=0',(user_id,hashlib.sha256(code.encode()).hexdigest(),int(time.time())))
            return result.rowcount==1
    def pair_redeem(self,code,device='Browser'):
        with sqlite_session(self.db) as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT user_id FROM pairing WHERE code_hash=? AND expires>? AND user_id IS NOT NULL AND redeemed=0',(hashlib.sha256(code.encode()).hexdigest(),int(time.time()))).fetchone()
            if not row:return None
            c.execute('UPDATE pairing SET redeemed=1 WHERE code_hash=?',(hashlib.sha256(code.encode()).hexdigest(),))
            token=secrets.token_urlsafe(32)
            c.execute('INSERT INTO sessions(token_hash,user_id,expires,device,created) VALUES(?,?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),row[0],int(time.time())+3600,str(device)[:80],int(time.time())))
            return token
