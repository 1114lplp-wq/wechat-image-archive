"""Windows clipboard file-drop collector. Standard library only; no network calls."""
from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from ctypes import wintypes
from pathlib import Path

from naming import make_filename, metadata

EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
BASE = Path(__file__).resolve().parent


def now():
    return dt.datetime.now().astimezone().isoformat(timespec='seconds')


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else default


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def enabled(config_path):
    return read_json(config_path, {}).get('enabled') is True


def validate_config(config):
    source, target = Path(config['source_root']), Path(config['target_folder'])
    if not source.is_absolute() or not source.is_dir() or source.name.lower() != 'rwtemp':
        raise ValueError('source_root must be an existing absolute WeChat temp/RWTemp directory')
    if not target.is_absolute():
        raise ValueError('target_folder must be absolute')
    source, target = source.resolve(), target.resolve()
    if target == source or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError('source and destination must be separate directories')
    return source, target


def allowed_source(path, source_root):
    path, root = Path(path), Path(source_root).resolve()
    if path.suffix.lower() not in EXTENSIONS:
        return False
    try:
        relative = path.resolve().relative_to(root)
    except (ValueError, OSError):
        return False
    return (len(relative.parts) >= 2 and
            bool(re.fullmatch(r'20\d{2}-(?:0[1-9]|1[0-2])', relative.parts[0])))


def image_bytes(data, extension):
    ext = extension.lower()
    return ((ext in {'.jpg', '.jpeg'} and data.startswith(b'\xff\xd8\xff')) or
            (ext == '.png' and data.startswith(b'\x89PNG\r\n\x1a\n')) or
            (ext == '.bmp' and data.startswith(b'BM')) or
            (ext == '.webp' and data[:4] == b'RIFF' and data[8:12] == b'WEBP'))


def unique_rename(source, requested):
    """On Windows rename never overwrites an existing destination."""
    requested = Path(requested)
    for number in range(10000):
        dest = requested if number == 0 else requested.with_name(
            requested.stem + '_' + str(number + 1) + requested.suffix)
        if dest.exists():
            continue
        try:
            Path(source).rename(dest)
            return dest
        except FileExistsError:
            continue
    raise RuntimeError('Too many filename collisions')


def run_ocr(image_path, output_path):
    powershell = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run(
        [str(powershell), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
         str(BASE / 'ocr-image.ps1'), '-ImagePath', str(image_path), '-OutputPath', str(output_path)],
        capture_output=True, timeout=75, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        # Log a technical failure only. Do not echo OCR contents into logs.
        raise RuntimeError('Windows OCR failed (exit %s)' % result.returncode)
    return read_json(output_path, {})


def ingest(source, config_path, state, ocr_fn=run_ocr):
    """Save before OCR. Only consume a path supplied by an active clipboard event."""
    config = read_json(config_path, {})
    if config.get('enabled') is not True:
        return 'disabled'
    source_root, target = validate_config(config)
    source = Path(source)
    if not allowed_source(source, source_root):
        return 'rejected_source'
    data = source.read_bytes()
    if not image_bytes(data, source.suffix):
        return 'rejected_format'
    digest = hashlib.sha256(data).hexdigest()
    known = state.setdefault('processed', {})
    if digest in known:
        return 'duplicate'
    if not enabled(config_path):
        return 'disabled'
    target.mkdir(parents=True, exist_ok=True)
    runtime = Path(config_path).parent
    incoming = target / ('.incoming-' + uuid.uuid4().hex + '.part')
    with incoming.open('xb') as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    if sha256(incoming) != digest:
        raise RuntimeError('Saved bytes failed integrity check; temporary copy retained')
    saved = unique_rename(incoming, target / ('待核对_图片_识别中_' + digest[:8] + source.suffix))
    record_path = runtime / 'records' / (digest + '.json')
    record = dict(sha256=digest, final_name=saved.name, saved_at=now(),
                  status='saved_pending_ocr', fields_verified={}, original_extension=source.suffix)
    atomic_json(record_path, record)
    known[digest] = {'name': saved.name, 'saved_at': record['saved_at']}
    atomic_json(runtime / 'state.json', state)
    # Track the file identity so a user's rename/edit during OCR always wins.
    saved_stat = saved.stat()
    try:
        cache = runtime / 'ocr-cache' / (digest + '.json')
        cache.parent.mkdir(parents=True, exist_ok=True)
        fields = metadata(ocr_fn(saved, cache))
        record['status'] = 'local_ocr_unverified'
        record['fields_ocr_unverified'] = fields
    except Exception as exc:
        fields = {}
        record.update(status='ocr_failed', error_type=type(exc).__name__)
    unchanged = False
    if saved.exists():
        current_stat = saved.stat()
        unchanged = ((current_stat.st_ino, current_stat.st_mtime_ns, current_stat.st_size) ==
                     (saved_stat.st_ino, saved_stat.st_mtime_ns, saved_stat.st_size) and
                     sha256(saved) == digest)
    if not unchanged:
        record.update(status='skipped_user_changed', reason='Saved image was renamed or edited during OCR')
    elif not enabled(config_path):
        record['status'] = 'saved_review_deferred'
    else:
        requested = target / make_filename(fields, source.suffix, digest)
        if requested != saved:
            saved = unique_rename(saved, requested)
        if sha256(saved) != digest:
            raise RuntimeError('Image changed after rename')
        record['final_name'] = saved.name
        known[digest]['name'] = saved.name
    record['updated_at'] = now()
    atomic_json(record_path, record)
    atomic_json(runtime / 'state.json', state)
    return record['status']


def clipboard_files(last_sequence=None):
    """Request native CF_HDROP; WeChat may export the image on demand."""
    user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
    user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    shell32.DragQueryFileW.restype = wintypes.UINT
    sequence = user32.GetClipboardSequenceNumber()
    if sequence == last_sequence:
        return sequence, []
    if not user32.OpenClipboard(None):
        return None, []
    try:
        sequence = user32.GetClipboardSequenceNumber()
        if not user32.IsClipboardFormatAvailable(15):
            return sequence, []
        drop = user32.GetClipboardData(15)
        if not drop:
            return None, []
        paths = []
        for index in range(min(shell32.DragQueryFileW(drop, 0xFFFFFFFF, None, 0), 100)):
            size = shell32.DragQueryFileW(drop, index, None, 0)
            buffer = ctypes.create_unicode_buffer(size + 1)
            shell32.DragQueryFileW(drop, index, buffer, size + 1)
            paths.append(Path(buffer.value))
        return sequence, paths
    finally:
        user32.CloseClipboard()


def monitor_clipboard(config_path, source_root, events, stop_event):
    # Keep reading copy events while a separate main loop performs slow OCR.
    sequence = None
    while not stop_event.is_set() and enabled(config_path):
        try:
            new_sequence, paths = clipboard_files(sequence)
            if new_sequence is not None and new_sequence != sequence:
                sequence = new_sequence
                for path in paths:
                    if allowed_source(path, source_root):
                        events.put(path)
        except Exception as exc:
            print(now(), 'clipboard_error', type(exc).__name__, flush=True)
            stop_event.wait(2)
        stop_event.wait(.25)


def lock_runtime(runtime):
    import msvcrt
    stream = (runtime / 'watcher.lock').open('a+b')
    if stream.tell() == 0:
        stream.write(b'0')
        stream.flush()
    stream.seek(0)
    try:
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        stream.close()
        return None
    return stream


def is_running(runtime):
    if not (runtime / 'watcher.lock').exists():
        return False
    stream = lock_runtime(runtime)
    if stream is None:
        return True
    stream.close()
    return False


def watch(config_path):
    runtime = config_path.parent
    runtime.mkdir(parents=True, exist_ok=True)
    lock = lock_runtime(runtime)
    if lock is None:
        return
    stop_event, reader = threading.Event(), None
    try:
        atomic_json(runtime / 'pid.json', {'pid': os.getpid(), 'started_at': now()})
        source_root, target = validate_config(read_json(config_path, {}))
        state = read_json(runtime / 'state.json', {'processed': {}})
        # Preserve all existing destination images, including user-renamed copies.
        if target.exists():
            for path in target.iterdir():
                if path.is_file() and path.suffix.lower() in EXTENSIONS:
                    try:
                        state['processed'].setdefault(sha256(path), {'name': path.name, 'existing': True})
                    except OSError:
                        pass
        atomic_json(runtime / 'state.json', state)
        events, pending = queue.Queue(), {}
        reader = threading.Thread(target=monitor_clipboard,
                                  args=(config_path, source_root, events, stop_event), daemon=True)
        reader.start()
        print(now(), 'collector_started', flush=True)
        while enabled(config_path):
            try:
                while True:
                    try:
                        path = events.get_nowait()
                    except queue.Empty:
                        break
                    pending[path] = (time.monotonic() + 30, None)
                for path, (deadline, previous_stat) in list(pending.items()):
                    if not enabled(config_path):
                        break
                    try:
                        stat = path.stat()
                        stamp = (stat.st_size, stat.st_mtime_ns)
                        if stat.st_size == 0 or stamp != previous_stat:
                            if time.monotonic() < deadline:
                                pending[path] = (deadline, stamp)
                                continue
                            raise TimeoutError('Export did not settle')
                        result = ingest(path, config_path, state)
                        print(now(), result, flush=True)
                        del pending[path]
                    except OSError:
                        if time.monotonic() >= deadline:
                            print(now(), 'export_unavailable', flush=True)
                            del pending[path]
                time.sleep(1)
            except Exception as exc:
                print(now(), 'collector_error', type(exc).__name__, flush=True)
                time.sleep(2)
        print(now(), 'collector_stopped', flush=True)
    finally:
        stop_event.set()
        if reader is not None:
            reader.join(timeout=2)
        pid_file = runtime / 'pid.json'
        if read_json(pid_file, {}).get('pid') == os.getpid():
            pid_file.unlink(missing_ok=True)
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['configure', 'start', 'stop', 'status', 'watch'])
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--source-root')
    parser.add_argument('--target-folder')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Windows is required')
    config_path = args.config.resolve()
    runtime = config_path.parent
    if args.action == 'configure':
        runtime.mkdir(parents=True, exist_ok=True)
        if is_running(runtime):
            parser.error('Stop this runtime before configuring it')
        if config_path.exists():
            parser.error('Configuration already exists; edit the stopped configuration or choose another RuntimeDir')
        if not args.source_root or not args.target_folder:
            parser.error('--source-root and --target-folder are required')
        config = dict(enabled=False, source_root=str(Path(args.source_root).resolve()),
                      target_folder=str(Path(args.target_folder).resolve()), version=1)
        validate_config(config)
        atomic_json(config_path, config)
        print('Configured (stopped):', config_path)
    elif args.action == 'status':
        print(json.dumps(dict(config_exists=config_path.exists(),
                              enabled=enabled(config_path), running=is_running(runtime)), ensure_ascii=True))
    elif args.action == 'watch':
        if enabled(config_path):
            watch(config_path)
    elif args.action == 'stop':
        if config_path.exists():
            config = read_json(config_path)
            config['enabled'] = False
            atomic_json(config_path, config)
        print('Stop requested. An in-flight local OCR can take up to 75 seconds to finish.')
    elif args.action == 'start':
        config = read_json(config_path)
        if not config:
            parser.error('Configure this runtime first')
        validate_config(config)
        if is_running(runtime):
            print('Already running; no second collector started.')
            return
        pythonw = Path(sys.executable).with_name('pythonw.exe')
        if not pythonw.exists():
            parser.error('pythonw.exe is required for hidden background mode')
        config['enabled'] = True
        atomic_json(config_path, config)
        with (runtime / 'watcher.log').open('ab') as log:
            process = subprocess.Popen(
                [str(pythonw), '-B', '-X', 'utf8', str(BASE / 'archive.py'), 'watch', '--config', str(config_path)],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
        for _ in range(20):
            if is_running(runtime):
                print('Running in background; no AI or network calls.')
                return
            if process.poll() is not None:
                break
            time.sleep(.25)
        raise RuntimeError('Collector did not start. Check watcher.log in the runtime directory.')


if __name__ == '__main__':
    main()
