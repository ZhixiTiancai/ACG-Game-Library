"""Create directory junctions and remove only links whose targets we verified."""
from pathlib import Path
import ctypes
import os
import struct


def is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def matches_link(path: Path, target: Path) -> bool:
    try:
        return is_link(path) and os.path.normcase(str(path.resolve())) == os.path.normcase(str(target.resolve()))
    except (OSError, RuntimeError):
        return False


def create_link(link: Path, target: Path):
    link, target = Path(link), Path(target).resolve()
    if not target.is_dir():
        raise ValueError('模组文件夹不存在，请重新导入。')
    if os.path.lexists(link) or is_link(link):
        raise ValueError(f'目标位置已存在同名内容，未覆盖：{link.name}')
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        os.symlink(target, link, target_is_directory=True)
        return
    if str(target).startswith('\\\\'):
        raise ValueError('使用功能需要本地磁盘上的模组库。')
    from ctypes import wintypes
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                               wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    api.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    api.DeviceIoControl.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    substitute = ('\\??\\' + str(target)).encode('utf-16-le')
    printable = str(target).encode('utf-16-le')
    paths = substitute + b'\0\0' + printable + b'\0\0'
    data = struct.pack('<IHHHHHH', 0xA0000003, 8 + len(paths), 0, 0, len(substitute),
                       len(substitute) + 2, len(printable)) + paths
    link.mkdir()
    handle = api.CreateFileW(str(link), 0x40000000, 7, None, 3, 0x00200000 | 0x02000000, None)
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error(); link.rmdir(); raise ctypes.WinError(error)
    try:
        buffer = ctypes.create_string_buffer(data)
        returned = wintypes.DWORD()
        if not api.DeviceIoControl(handle, 0x000900A4, buffer, len(data), None, 0, ctypes.byref(returned), None):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        api.CloseHandle(handle)
        # Failure cleanup is deliberately non-recursive and never follows a link.
        if not is_link(link):
            link.rmdir()


def remove_link(link: Path, target: Path):
    if not os.path.lexists(link) and not is_link(link):
        return
    if not matches_link(link, target):
        raise ValueError(f'该位置已被其他内容替换，未删除：{link}')
    if os.name == 'nt' and link.is_junction():
        os.rmdir(link)
    else:
        link.unlink()
