"""Restore a local demo backup into a NEW disposable drill database, then remove it."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def kube(namespace, *arguments, **kwargs):
    return subprocess.run(['kubectl', '--context=minikube', '-n', namespace, 'exec', '-i',
                           'seatlock-postgres-0', '--', *arguments], check=True, timeout=120, **kwargs)


def counts(namespace, database):
    entries = []
    for table in ('events', 'seats', 'holds', 'audit_events'):
        entries.append("'%s',(SELECT json_build_object('count',count(*),'checksum',md5(coalesce(string_agg(row_to_json(t)::text, E'\\n' ORDER BY id),''))) FROM %s t)" % (table, table))
    query = 'SELECT json_build_object('+','.join(entries)+');'
    result = kube(namespace, 'psql', '-U', 'seatlock', '-d', database, '-At', '-c', query,
                  capture_output=True, text=True)
    return json.loads(result.stdout)


def main():
    if subprocess.check_output(['kubectl','config','current-context'], text=True).strip() != 'minikube':
        raise SystemExit('Select the local minikube context first.')
    # PostgreSQL's dump is transactionally consistent; compare counts before and
    # after to refuse evidence if traffic changed the source during this drill.
    before = counts('seatlock', 'seatlock')
    database = 'seatlock_restore_'+secrets.token_hex(6)
    artifacts = ROOT/'.artifacts'
    artifacts.mkdir(exist_ok=True)
    backup = artifacts/(database+'.dump')
    descriptor = os.open(backup, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as handle:
        kube('seatlock', 'pg_dump', '-U', 'seatlock', '-d', 'seatlock', '-Fc', '--no-owner',
             '--no-privileges', stdout=handle)
    assert before == counts('seatlock','seatlock'), 'Source changed; pause booking traffic and rerun.'
    kube('seatlock-drill', 'createdb', '-U', 'seatlock', database)
    try:
        with backup.open('rb') as handle:
            kube('seatlock-drill', 'pg_restore', '-U', 'seatlock', '-d', database,
                 '--no-owner', '--no-privileges', '--exit-on-error', stdin=handle)
        restored = counts('seatlock-drill', database)
        assert restored == before
        report = {'time':datetime.now(timezone.utc).isoformat(),'source_namespace':'seatlock',
                  'restore_namespace':'seatlock-drill','new_disposable_database':True,
                  'source_counts':before,'restored_counts':restored,'backup_bytes':backup.stat().st_size,
                  'backup_location':'Ignored .artifacts/; private mode 600',
                  'verification':'pg_restore succeeded, schema/constraints restored, all four table counts AND row-content checksums match',
                  'cleanup':'Disposable restore DB dropped; main/drill application databases unchanged'}
    finally:
        kube('seatlock-drill', 'dropdb', '-U', 'seatlock', database)
    (ROOT/'docs/evidence/backup-restore.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Consistent backup restored to a separate disposable DB; all table counts match.')


if __name__ == '__main__':
    main()
