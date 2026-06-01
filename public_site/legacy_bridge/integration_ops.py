"""אבחון, הפעלה, כיבוי ולוגים לדף אינטגרציה."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from django.conf import settings

from .health_status import _BACKEND_HEALTH_PATHS, check_backends_health

SERVICE_SCRIPTS: dict[str, tuple[str, int, str]] = {
    'engine': ('beckend_toto.py', 5001, 'מנוע טוטו'),
    'auth': ('auth_server.py', 5002, 'התחברות קלאסית'),
    'wallet': ('wallet_server.py', 5003, 'ארנק / הזמנות'),
    'lotto_api': ('server.py', 5000, 'API לוטו'),
}

LOG_FILES = ('integration.log', 'legacy_pids.log')


def _data_dir() -> Path:
    d = Path(settings.BASE_DIR) / 'data'
    d.mkdir(parents=True, exist_ok=True)
    return d


def append_integration_log(line: str) -> None:
    path = _data_dir() / 'integration.log'
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    with path.open('a', encoding='utf-8') as f:
        f.write(f'[{ts}] {line}\n')


def _run_subprocess(cmd: list[str], cwd: Path, timeout: int = 45) -> tuple[int, str]:
    try:
        r = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding='utf-8',
            errors='replace',
        )
        out = (r.stdout or '') + (r.stderr or '')
        return r.returncode, out.strip()[:4000]
    except subprocess.TimeoutExpired:
        return -1, 'תם הזמן להפעלה'
    except Exception as exc:
        return -1, str(exc)[:500]


def _diagnose_service(key: str, health: dict) -> str:
    h = health.get(key) or {}
    parts = [f'שירות={key}']
    if h.get('disabled'):
        parts.append('LEGACY_SERVICES_ENABLED=false')
    if h.get('port'):
        parts.append(f"port={h['port']} port_up={h.get('port_up')}")
    direct = h.get('direct') or {}
    django = h.get('django') or {}
    if direct.get('error'):
        parts.append(f"direct: {direct['error']}")
    elif direct.get('code'):
        parts.append(f"direct HTTP {direct['code']}")
    if django.get('error'):
        parts.append(f"django: {django['error']}")
    elif django.get('code'):
        parts.append(f"django proxy {django['code']}")
    path = _BACKEND_HEALTH_PATHS.get(key, '')
    if path:
        parts.append(f'check={path}')
    return ' · '.join(parts)


def try_fix_service(service_key: str) -> dict:
    """מנסה להפעיל שירות בודד או את כל הסקריפטים."""
    root = Path(settings.BASE_DIR)
    append_integration_log(f'פתור בעיה: בקשה עבור {service_key}')

    if service_key == 'all':
        script = root / 'scripts' / 'start_legacy_background.py'
        if not script.is_file():
            msg = 'קובץ start_legacy_background.py לא נמצא'
            append_integration_log(msg)
            return {'ok': False, 'message': msg}
        code, out = _run_subprocess([sys.executable, str(script)], root)
        append_integration_log(f'start_all exit={code}\n{out or "(ללא פלט)"}')
        time.sleep(2.5)
        health = check_backends_health()
        ok = all(v.get('ok') for v in health.values())
        return {
            'ok': ok,
            'message': 'כל השירותים פעילים' if ok else 'הופעלו תהליכים – חלק מהשירותים עדיין כבויים. ראה לוגים.',
            'health': health,
        }

    if service_key not in SERVICE_SCRIPTS:
        return {'ok': False, 'message': f'שירות לא מוכר: {service_key}'}

    script_name, port, label = SERVICE_SCRIPTS[service_key]
    script_path = root / script_name
    health_before = check_backends_health()
    append_integration_log(_diagnose_service(service_key, health_before))

    if not script_path.is_file():
        msg = f'לא נמצא {script_name}'
        append_integration_log(msg)
        return {'ok': False, 'message': msg}

    h = health_before.get(service_key) or {}
    if h.get('port_up') and not h.get('ok'):
        msg = (
            f'{label}: הפורט {port} פתוח אך הבדיקה נכשלה. '
            'ייתכן שהתהליך תקוע – נסה להפעיל מחדש את הקונטיינר ב-Railway.'
        )
        append_integration_log(msg)
        return {'ok': False, 'message': msg}

    if h.get('ok'):
        return {'ok': True, 'message': f'{label} כבר פעיל'}

    svc_log = _data_dir() / f'legacy_{Path(script_name).stem}.log'
    log_fh = svc_log.open('a', encoding='utf-8')
    log_fh.write(f'\n=== fix {time.strftime("%Y-%m-%d %H:%M:%S")} port={port} ===\n')
    log_fh.flush()
    proc = subprocess.Popen(
        [sys.executable, str(script_path)],
        cwd=str(root),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
    )
    append_integration_log(f'הופעל {script_name} pid={proc.pid} port={port}')
    time.sleep(2.5)

    if proc.poll() is not None:
        tail = ' / '.join(read_log_tail(svc_log.name, 10))
        append_integration_log(f'{script_name} קרס מיד (exit={proc.returncode}): {tail[:300]}')
        return {
            'ok': False,
            'message': (
                f'{label}: התהליך קרס מיד (קוד {proc.returncode}). '
                f'סיבה אחרונה: {tail[:220] or "ראה לוגים"}'
            ),
        }

    health_after = check_backends_health()
    append_integration_log(_diagnose_service(service_key, health_after))
    ok = bool((health_after.get(service_key) or {}).get('ok'))
    if ok:
        return {'ok': True, 'message': f'{label} הופעל בהצלחה (פורט {port})'}
    return {
        'ok': False,
        'message': (
            f'{label}: ניסיון הפעלה בוצע (pid {proc.pid}) אך השירות עדיין לא עונה. '
            'ב-Railway ודא LEGACY_AUTO_START=true ופרוס מחדש.'
        ),
    }


def _last_pid_for_script(script_name: str) -> int | None:
    """ה-PID האחרון שתועד עבור הסקריפט ב-legacy_pids.log."""
    log_path = _data_dir() / 'legacy_pids.log'
    if not log_path.is_file():
        return None
    pid = None
    try:
        for line in log_path.read_text(encoding='utf-8', errors='replace').splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[0] == script_name:
                try:
                    pid = int(parts[2])
                except ValueError:
                    continue
    except OSError:
        return None
    return pid


def _kill_service_process(service_key: str) -> int | None:
    """מנסה לעצור את תהליך השירות לפי ה-PID שתועד. best-effort."""
    from .service_registry import SERVICES

    script_name = SERVICES[service_key]['script']
    pid = _last_pid_for_script(script_name)
    if not pid:
        return None
    try:
        os.kill(pid, signal.SIGTERM)
        return pid
    except OSError:
        return None


def stop_service(service_key: str) -> dict:
    """מכבה שירות: מסמן «מושבת» (נשמר ב-DB) ומנסה לעצור את התהליך."""
    from .service_registry import SERVICES, service_label, set_service_enabled

    if service_key not in SERVICES:
        return {'ok': False, 'message': f'שירות לא מוכר: {service_key}'}

    set_service_enabled(service_key, False, note='כובה מהדשבורד')
    killed = _kill_service_process(service_key)
    append_integration_log(
        f'כיבוי {service_key}: disabled=true killed_pid={killed if killed else "—"}',
    )
    label = service_label(service_key)
    note = f'{label} כובה.'
    if killed:
        note += f' התהליך (pid {killed}) נעצר.'
    return {'ok': True, 'message': note}


def enable_service(service_key: str) -> dict:
    """מפעיל שירות: מסמן «מופעל» ומנסה להריץ אותו מחדש."""
    from .service_registry import SERVICES, service_label, set_service_enabled

    if service_key not in SERVICES:
        return {'ok': False, 'message': f'שירות לא מוכר: {service_key}'}

    set_service_enabled(service_key, True, note='הופעל מהדשבורד')
    append_integration_log(f'הפעלה {service_key}: disabled=false')
    result = try_fix_service(service_key)
    label = service_label(service_key)
    return {
        'ok': True,
        'message': f'{label} סומן כמופעל. {result.get("message", "")}'.strip(),
    }


def read_log_tail(filename: str, max_lines: int = 250) -> list[str]:
    path = _data_dir() / filename
    if not path.is_file():
        return [f'(אין קובץ {filename} עדיין)']
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError as exc:
        return [f'שגיאת קריאה: {exc}']
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return lines
    return lines[-max_lines:]


def get_integration_logs(max_lines: int = 250) -> dict:
    """כל קבצי הלוג הרלוונטיים לדף הלוגים."""
    sections = {}
    for name in LOG_FILES:
        sections[name] = read_log_tail(name, max_lines)
    return {'sections': sections, 'log_dir': str(_data_dir())}
