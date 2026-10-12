"""Verify scanners fail on synthetic controls; never register or use the fake token."""
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import string
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FINGERPRINT = 'A035C8C19219BA821ECEA86B64E628F8D684696D'


def scan(fixture):
    return subprocess.run(['docker','run','--rm','-v',str(fixture)+':/fixture:ro',
                           '-v',str(ROOT/'.gitleaks.toml')+':/config.toml:ro',
                           'ghcr.io/gitleaks/gitleaks:v8.30.1','dir','/fixture','--config','/config.toml',
                           '--redact','--exit-code','1'], capture_output=True, text=True, timeout=60)


def main():
    with tempfile.TemporaryDirectory(prefix='seatlock-controls-') as temporary:
        fixture = Path(temporary)
        (fixture/'security/reports').mkdir(parents=True)
        public = fixture/'security/reports/backend.json'
        public.write_text('GPG_KEY='+FINGERPRINT+'\n')
        assert scan(fixture).returncode == 0, 'Public fingerprint exception failed'
        fake = 'ghp_'+''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(36))
        (fixture/'sample.env').write_text('GITHUB_TOKEN='+fake+'\n')
        # An unrelated secret on the SAME line as the allowed public fingerprint
        # must still be detected. No file/path or whole-line exemption is allowed.
        public.write_text('GPG_KEY='+FINGERPRINT+' GITHUB_TOKEN='+fake+'\n')
        detected = scan(fixture)
        assert detected.returncode == 1 and 'leaks found: 2' in detected.stderr, 'Scanner failed negative control'
        unsafe = fixture/'unsafe.py'
        unsafe.write_text('import subprocess\nimport sys\nsubprocess.run(sys.argv[1], shell=True)\n')
        bandit = ROOT/'backend/.venv/bin/bandit'
        command = [str(bandit)] if bandit.exists() else ['bandit']
        sast = subprocess.run(command+[str(unsafe),'-ll','-f','json'], capture_output=True, text=True, timeout=60)
        findings = json.loads(sast.stdout)['results']
        assert sast.returncode == 1 and any(f['test_id']=='B602' for f in findings)
        report = {'time':datetime.now(timezone.utc).isoformat(),
                  'gitleaks':{'version':'8.30.1','config':'.gitleaks.toml','exit_code':1,'synthetic_findings':2,
                             'locations':['sample.env','security/reports/backend.json'],
                             'public_fingerprint_only_passes':True,'secret_on_same_line_still_fails':True,
                             'note':'Unused synthetic PAT; no path or whole-line exceptions.'},
                  'bandit':{'exit_code':1,'finding':'B602','note':'Disposable shell=True fixture; no unsafe command executed.'}}
        (ROOT/'security/reports/gate-controls.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Gate controls passed: exact public value allowed; both fake secrets and B602 blocked.')


if __name__ == '__main__':
    main()
