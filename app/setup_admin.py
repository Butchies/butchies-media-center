#!/usr/bin/env python3
"""Local one-time administrator setup. No passwords are embedded in the package."""
import os, getpass
from pathlib import Path
from auth import Accounts
ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('BMC_DATA',str(ROOT/'data')))
DATA.mkdir(parents=True,exist_ok=True)
accounts=Accounts(DATA/'accounts.sqlite')
if accounts.count():
    print('Ein Administratorkonto existiert bereits. Keine Aenderung vorgenommen.')
    raise SystemExit(1)
username='sven_new02'
print('Ersteinrichtung fuer Administrator:',username)
password=getpass.getpass('Passwort eingeben (mindestens 6 Zeichen): ')
confirm=getpass.getpass('Passwort wiederholen: ')
if password != confirm:
    print('Passwoerter stimmen nicht ueberein.')
    raise SystemExit(2)
try:
    accounts.register_first_admin(username,password)
except ValueError as e:
    print('Einrichtung fehlgeschlagen:',e)
    raise SystemExit(3)
print('Administratorkonto angelegt. Passwort wird nicht im Paket gespeichert.')
