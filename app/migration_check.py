#!/usr/bin/env python3
"""Read-only assessment of RC20 test-data and dedicated installation data."""
import os,sqlite3,sys
from pathlib import Path
old=Path('/mnt/HD/HD_a2/Public/ButchiesMediaCenter/test-data')
new=Path('/mnt/HD/HD_a2/butchiesmediacenter-data')
for label,folder in [('RC20',old),('WD_APP',new)]:
 print(label, 'directory_present=',folder.is_dir())
 for db in ('accounts.sqlite','library.sqlite'):
  p=folder/db
  print(' ',db,'present=',p.is_file(),'bytes=',p.stat().st_size if p.is_file() else 0)
print('READ-ONLY: no accounts or media have been migrated')
