#!/usr/bin/env python3
"""Neutralize identifying landmark wording in imported review text, including nested JSON."""
import csv
import os
import sqlite3
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.seed_review_demo import check_target
from scripts.import_case_anonymized import ALLOWLIST

REPLACEMENTS = (
    ('grey memorial with Stars of David', 'grey stone marker'),
    ('white memorial post with Stars of David', 'white landmark post'),
    ('memorial post', 'landmark post'),
)

def main():
    path = check_target()
    changes = []
    with sqlite3.connect(path) as conn:
        for table, where in ALLOWLIST:
            columns = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
            rows = conn.execute(f'SELECT rowid,* FROM "{table}" WHERE {where}', {'sector': 'FIELD-TEST-01'}).fetchall()
            for row in rows:
                for column, old in zip(columns, row[1:]):
                    if not isinstance(old, str):
                        continue
                    new = old
                    for source, target in REPLACEMENTS:
                        new = new.replace(source, target)
                    if new != old:
                        conn.execute(f'UPDATE "{table}" SET "{column}"=? WHERE rowid=?', (new, row[0]))
                        changes.append((table, column, row[0]))
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Integrity check failed')
    writer = csv.writer(sys.stdout)
    writer.writerow(['table', 'column', 'row_id'])
    writer.writerows(changes)

if __name__ == '__main__':
    main()
