"""Local settings and read-only discovery of external XXMI installations."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from dataclasses import dataclass

VERSION = '0.7.0'
GAMES = {
    'SRMI': {'name': '崩坏：星穹铁道', 'short': '星穹铁道', 'en': 'HONKAI: STAR RAIL', 'color': '#ae9aff'},
    'ZZMI': {'name': '绝区零', 'short': '绝区零', 'en': 'ZENLESS ZONE ZERO', 'color': '#e8c36c'},
    'EFMI': {'name': '明日方舟：终末地', 'short': '终末地', 'en': 'ARKNIGHTS: ENDFIELD', 'color': '#85c8b4'},
}


def app_root() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent


class Settings:
    def __init__(self, root: Path):
        self.root = root
        self.path = root / 'data' / 'settings.json'
        self.values = {'schema': 1, 'game': 'SRMI', 'xxmi_root': '', 'scan_on_start': True,
                       'library_root': str(root / 'Library'), 'theme_color': 'purple',
                       'theme_transparency': 0, 'background_path': '', 'check_updates_on_start': True}
        self.load_error = ''
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(saved, dict):
                    raise ValueError('设置必须是 JSON 对象')
                for key in self.values:
                    if key in saved and type(saved[key]) is type(self.values[key]):
                        self.values[key] = saved[key]
            except (ValueError, OSError) as exc:
                self.load_error = f'原设置无法读取，已使用默认值：{exc}'
        if self.values['game'] not in GAMES:
            self.values['game'] = 'SRMI'
        if not self.values['library_root'].strip():
            self.values['library_root'] = str(root / 'Library')
        if self.values['theme_color'] not in {'purple','red','green','yellow','blue','black','white'}:
            self.values['theme_color'] = 'purple'
        self.values['theme_transparency'] = max(0,min(100,self.values['theme_transparency']))

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.json.tmp')
        temp.write_text(json.dumps(self.values, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, self.path)

    def library_path(self, game: str) -> Path:
        if game not in GAMES:
            raise ValueError('不支持的游戏')
        return Path(self.values['library_root']) / game


@dataclass(frozen=True)
class Installation:
    root: Path
    exe: Path
    version: str
    games: tuple[str, ...]

    def target(self, game: str) -> Path:
        if game not in GAMES:
            raise ValueError('不支持的游戏')
        return self.root / game / 'Mods'


def file_version(path: Path) -> str:
    """Read the PE version resource; never load or execute the target file."""
    if os.name != 'nt':
        return ''
    try:
        api = ctypes.windll.version
        handle = ctypes.c_uint(0)
        size = api.GetFileVersionInfoSizeW(str(path), ctypes.byref(handle))
        if not size:
            return ''
        buffer = ctypes.create_string_buffer(size)
        if not api.GetFileVersionInfoW(str(path), 0, size, buffer):
            return ''
        value, length = ctypes.c_void_p(), ctypes.c_uint()
        if not api.VerQueryValueW(buffer, '\\', ctypes.byref(value), ctypes.byref(length)):
            return ''
        data = ctypes.cast(value, ctypes.POINTER(ctypes.c_uint32))
        if length.value < 16 or data[0] != 0xFEEF04BD:
            return ''
        return '.'.join(str(n) for n in [data[2] >> 16, data[2] & 0xFFFF, data[3] >> 16])
    except (OSError, AttributeError, ValueError):
        return ''


def inspect_installation(candidate: str | Path) -> Installation | None:
    """Accept an installation root, Resources/Bin, or the exact executable."""
    try:
        path = Path(candidate).expanduser().resolve()
        if path.is_file():
            if path.name.casefold() != 'xxmi launcher.exe':
                return None
            path = path.parent
        roots = [path]
        if path.name.casefold() == 'bin' and path.parent.name.casefold() == 'resources':
            roots.insert(0, path.parent.parent)
        for root in roots:
            exe = root / 'Resources' / 'Bin' / 'XXMI Launcher.exe'
            if not exe.is_file():
                continue
            # Recognize the actual portable layout, not unrelated same-name files.
            if not (root / 'XXMI Launcher Config.json').is_file() and not any((root / g / 'd3dx.ini').is_file() for g in GAMES):
                continue
            version = file_version(exe)
            if not version:
                try:
                    cfg = json.loads((root / 'XXMI Launcher Config.json').read_text(encoding='utf-8-sig'))
                    version = cfg['Packages']['packages']['Launcher']['deployed_version']
                except (KeyError, TypeError, ValueError, OSError):
                    version = ''
            games = tuple(g for g in GAMES if (root / g / 'd3dx.ini').is_file())
            return Installation(root, exe, version or '未知版本', games)
    except (OSError, ValueError, RuntimeError):
        pass
    return None


def common_search_roots() -> list[Path]:
    home = Path.home()
    roots = [Path(os.environ.get('APPDATA', str(home / 'AppData/Roaming'))) / 'XXMI Launcher',
             Path(os.environ.get('LOCALAPPDATA', str(home / 'AppData/Local'))) / 'XXMI Launcher',
             home / 'Desktop', home / 'Downloads']
    for drive in 'CDEFGH':
        base = Path(f'{drive}:/')
        for name in ['game tool', 'Games', 'Tools', 'XXMI', 'XXMI Launcher']:
            roots.append(base / name)
    if os.name == 'nt':
        import winreg
        for hive in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
            for branch in [r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
                           r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall']:
                try:
                    with winreg.OpenKey(hive, branch) as key:
                        for i in range(winreg.QueryInfoKey(key)[0]):
                            try:
                                with winreg.OpenKey(key, winreg.EnumKey(key, i)) as entry:
                                    name = winreg.QueryValueEx(entry, 'DisplayName')[0]
                                    if 'xxmi' in str(name).casefold():
                                        location = winreg.QueryValueEx(entry, 'InstallLocation')[0]
                                        if location:
                                            roots.append(Path(location))
                            except OSError:
                                continue
                except OSError:
                    continue
    return roots


def discover_installations(search_roots=None, max_depth=6, max_directories=4500) -> list[Installation]:
    """Bounded discovery. Skip mod content, junctions and large runtime folders."""
    skip = {'mods', 'modlibrary', 'library', 'node_modules', '.git', '$recycle.bin',
            'windows', 'system volume information', 'shadercache', 'shaderfixes',
            'core', 'locale', 'language', 'themes', 'assets', '_internal', 'backups'}
    stack = [(Path(p), 0) for p in (search_roots if search_roots is not None else common_search_roots())]
    seen, found = set(), {}
    while stack and len(seen) < max_directories:
        path, depth = stack.pop()
        key = str(path.absolute()).casefold()
        if key in seen:
            continue
        seen.add(key)
        try:
            if not path.is_dir() or path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                continue
            installation = inspect_installation(path)
            if installation:
                found[str(installation.root).casefold()] = installation
                continue
            if depth >= max_depth:
                continue
            for child in path.iterdir():
                if child.name.casefold() not in skip and child.is_dir():
                    stack.append((child, depth + 1))
        except (OSError, ValueError):
            continue
    def score(item):
        version = tuple(int(x) for x in re.findall(r'\d+', item.version)[:3])
        return (len(item.games), version, -len(item.root.parts))
    return sorted(found.values(), key=score, reverse=True)


class LaunchCancelled(Exception):
    """The user declined the normal Windows elevation prompt."""


def shell_launch(exe: Path, arguments: list[str], cwd: Path):
    """Use the Windows shell so requireAdministrator manifests can show UAC."""
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG),
                    ('hwnd', wintypes.HWND), ('lpVerb', wintypes.LPCWSTR),
                    ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR),
                    ('lpDirectory', wintypes.LPCWSTR), ('nShow', ctypes.c_int),
                    ('hInstApp', wintypes.HINSTANCE), ('lpIDList', ctypes.c_void_p),
                    ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY),
                    ('dwHotKey', wintypes.DWORD), ('hIcon', wintypes.HANDLE),
                    ('hProcess', wintypes.HANDLE)]

    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000100 | 0x00000040 | 0x00000400  # NOASYNC | NOCLOSEPROCESS | NO_UI (errors only)
    info.lpVerb = 'runas'  # Elevate XXMI through normal UAC, not ACG itself.
    info.lpFile = str(exe)
    info.lpParameters = subprocess.list2cmdline(arguments)
    info.lpDirectory = str(cwd)
    info.nShow = 1
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == 1223:
            raise LaunchCancelled('已取消 XXMI 的权限请求。')
        raise ctypes.WinError(error)
    if info.hProcess:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(info.hProcess)


def open_xxmi(installation: Installation, game: str):
    if game not in GAMES or not installation.exe.is_file():
        raise ValueError('XXMI 路径无效，请在设置中重新选择。')
    # --xxmi chooses the importer and opens its UI; no --nogui / auto game launch.
    if os.name == 'nt':
        return shell_launch(installation.exe, ['--xxmi', game], installation.exe.parent)
    return subprocess.Popen([str(installation.exe), '--xxmi', game], cwd=str(installation.exe.parent))
