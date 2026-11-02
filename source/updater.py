"""GitHub Releases updates; downloads and app-only replacement, never user data."""
from __future__ import annotations
from dataclasses import dataclass
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

from acg_core import VERSION

REPOSITORY = 'ZhixiTiancai/ACG-Game-Library'
REPOSITORY_URL = 'https://github.com/' + REPOSITORY
RELEASES_URL = REPOSITORY_URL + '/releases'
LATEST_API = 'https://api.github.com/repos/' + REPOSITORY + '/releases/latest'
APP_ID = 'ACG-Game-Library'
MANIFEST = 'release-manifest.json'
EXE = 'ACG Game Library.exe'
DIRECTORIES = {'_internal', 'source', 'licenses'}
ROOT_FILES = {EXE, MANIFEST, 'README.md', 'THIRD-PARTY.txt', '使用说明.md', 'RELEASE_NOTES.md'}
MAX_PACKAGE = 1024**3


class UpdateError(ValueError): pass
class Cancelled(UpdateError): pass


def version_tuple(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?',value)
    if not match: raise UpdateError('版本号格式不受支持。')
    return tuple(int(n or 0) for n in match.groups())


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024**2), b''): digest.update(chunk)
    return digest.hexdigest()


def safe_relative(value):
    if not isinstance(value,str) or '\\' in value: raise UpdateError('更新包路径无效。')
    path = PurePosixPath(value)
    if not value or path.is_absolute() or PureWindowsPath(value).drive or any(p in {'.','..'} or p.rstrip(' .') != p or re.search(r'[<>:"|?*\x00-\x1f]',p) for p in path.parts):
        raise UpdateError('更新包包含不安全的路径。')
    if any(p.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*{f'COM{i}' for i in range(1,10)},*{f'LPT{i}' for i in range(1,10)}} for p in path.parts):
        raise UpdateError('更新包包含保留的 Windows 文件名。')
    if path.parts[0] not in DIRECTORIES and (len(path.parts) != 1 or value not in ROOT_FILES):
        raise UpdateError('更新包试图改动用户数据或未允许的目录。')
    return path


def is_link(path):
    return path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction())


def child(root, relative):
    root = Path(root).resolve(); result = root / Path(relative)
    if result.resolve() == root or not result.resolve().is_relative_to(root):
        raise UpdateError('更新路径超出启动器目录。')
    if is_link(result): raise UpdateError('更新目标是外部目录链接，未改动该位置。')
    return result


class SecureRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme != 'https' or parsed.hostname not in {'github.com','api.github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'}:
            raise UpdateError('更新下载被重定向至未允许的地址。')
        return super().redirect_request(request,fp,code,message,headers,newurl)


def request_url(url, binary=False):
    parsed = urllib.parse.urlparse(url)
    allowed = parsed.scheme == 'https' and (
        parsed.hostname == 'api.github.com' and parsed.path.startswith('/repos/' + REPOSITORY + '/releases')
        or parsed.hostname == 'github.com' and parsed.path.startswith('/' + REPOSITORY + '/releases/download/'))
    if not allowed: raise UpdateError('更新地址不属于指定的 GitHub 仓库。')
    request = urllib.request.Request(url,headers={'User-Agent':'ACG-Game-Library/'+VERSION,
        'Accept':'application/octet-stream' if binary else 'application/vnd.github+json',
        'X-GitHub-Api-Version':'2022-11-28'})
    return urllib.request.build_opener(SecureRedirect()).open(request,timeout=30)


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    name: str
    download_url: str
    size: int
    sha256: str
    checksum_url: str
    notes: str


def parse_release(data):
    if not isinstance(data,dict): raise UpdateError('更新服务返回的内容无效。')
    version = str(data.get('tag_name','')); version_tuple(version)
    if data.get('draft') or data.get('prerelease'): raise UpdateError('此版本不是正式发行版。')
    plain = version.removeprefix('v')
    filename = f'ACG-Game-Library-v{plain}-windows-x64.zip'
    assets = data.get('assets',[])
    package = next((a for a in assets if a.get('name') == filename and a.get('state','uploaded') == 'uploaded'),None)
    checksum = next((a for a in assets if a.get('name') == filename+'.sha256'),None)
    if not package: raise UpdateError('此发行版尚未上传 Windows 更新包，请稍后重试。')
    digest = str(package.get('digest') or '')
    sha = digest[7:].lower() if re.fullmatch(r'sha256:[0-9a-fA-F]{64}',digest) else ''
    if not sha and not checksum: raise UpdateError('此发行版缺少 SHA-256 校验信息。')
    size = package.get('size',0)
    if type(size) is not int or not 0 < size <= MAX_PACKAGE: raise UpdateError('更新包大小无效。')
    return Release(plain,RELEASES_URL+'/tag/'+version,filename,str(package.get('browser_download_url','')),size,sha,
        str(checksum.get('browser_download_url','')) if checksum else '',str(data.get('body',''))[:20000])


def check_latest():
    try:
        with request_url(LATEST_API) as response:
            payload = response.read(2*1024**2+1)
        if len(payload) > 2*1024**2: raise UpdateError('更新信息过大。')
        return parse_release(json.loads(payload))
    except urllib.error.HTTPError as exc:
        if exc.code == 404: return None
        if exc.code in {403,429}: raise UpdateError('GitHub 暂时限制了检查频率，请稍后重试或查看发行页面。') from exc
        raise UpdateError(f'更新检查失败（HTTP {exc.code}），请稍后重试。') from exc
    except (urllib.error.URLError,TimeoutError,OSError,json.JSONDecodeError) as exc:
        raise UpdateError('无法连接 GitHub 更新服务，请检查网络后重试。') from exc


def verify_payload(stage, expected_version):
    stage = Path(stage)
    manifest_path = stage / MANIFEST
    if not manifest_path.is_file() or manifest_path.stat().st_size > 2*1024**2: raise UpdateError('更新包缺少有效清单。')
    try: manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    except (ValueError,OSError) as exc: raise UpdateError('更新清单无法读取。') from exc
    if manifest.get('app_id') != APP_ID or manifest.get('version') != expected_version or manifest.get('platform') != 'windows-x64':
        raise UpdateError('更新包的软件、版本或平台不匹配。')
    files = manifest.get('files')
    if not isinstance(files,dict) or EXE not in files or not any(k.startswith('_internal/') for k in files):
        raise UpdateError('更新包不完整。')
    normalized = set()
    for name, digest in files.items():
        safe_relative(name)
        if name.casefold() in normalized or not re.fullmatch(r'[0-9a-f]{64}',str(digest)):
            raise UpdateError('更新清单包含重复路径或无效校验值。')
        normalized.add(name.casefold())
        path = child(stage,name)
        if not path.is_file() or file_hash(path) != digest: raise UpdateError(f'更新文件校验失败：{name}')
    actual = set()
    for root, dirs, names in os.walk(stage,followlinks=False):
        for name in dirs + names:
            if is_link(Path(root)/name): raise UpdateError('更新包中不能包含文件链接。')
        for name in names: actual.add((Path(root)/name).relative_to(stage).as_posix())
    if actual != set(files) | {MANIFEST}: raise UpdateError('更新包存在清单以外的文件。')
    return manifest


def extract_package(package, destination, version):
    destination = Path(destination)
    destination.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(package) as archive:
        entries = archive.infolist()
        if len(entries) > 50000 or sum(e.file_size for e in entries) > MAX_PACKAGE:
            raise UpdateError('更新包解压后过大。')
        names = set()
        for entry in entries:
            raw = entry.filename.rstrip('/')
            if not raw.startswith('ACG Game Library/'):
                if raw == 'ACG Game Library' and entry.is_dir(): continue
                raise UpdateError('更新包目录结构无效。')
            relative = raw[len('ACG Game Library/'):]
            path = safe_relative(relative)
            if stat.S_ISLNK(entry.external_attr >> 16) or relative.casefold() in names:
                raise UpdateError('更新包包含链接或重复路径。')
            names.add(relative.casefold())
            target = child(destination,path)
            if entry.is_dir(): target.mkdir(parents=True,exist_ok=True)
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(entry) as source, target.open('wb') as output: shutil.copyfileobj(source,output)
    verify_payload(destination,version)
    return destination


def download_release(release, root, progress=lambda percent:None, cancelled=lambda:False):
    work = Path(root)/'data'/'updates'/uuid.uuid4().hex
    work.mkdir(parents=True)
    package = work/release.name
    expected = release.sha256
    if not expected:
        with request_url(release.checksum_url,True) as response: content = response.read(16385)
        match = re.fullmatch(rb'([0-9a-fA-F]{64})(?:[ \t]+[^\r\n]+)?\s*',content)
        if not match: raise UpdateError('无法读取更新包校验值。')
        expected = match[1].decode().lower()
    try:
        downloaded = 0; digest = hashlib.sha256()
        with request_url(release.download_url,True) as response, package.open('wb') as output:
            while True:
                if cancelled(): raise Cancelled('已取消更新下载。')
                chunk = response.read(256*1024)
                if not chunk: break
                downloaded += len(chunk)
                if downloaded > release.size or downloaded > MAX_PACKAGE: raise UpdateError('更新包大小与发行信息不一致。')
                output.write(chunk); digest.update(chunk); progress(min(95,downloaded*95//release.size))
        if downloaded != release.size or digest.hexdigest() != expected: raise UpdateError('SHA-256 校验失败，更新包未被安装。')
        if cancelled(): raise Cancelled('已取消更新下载。')
        stage = extract_package(package,work/'staging',release.version)
        progress(100)
        plan = work/'install-plan.json'
        plan.write_text(json.dumps({'schema':1,'root':str(Path(root).resolve()),'stage':str(stage.resolve()),
            'version':release.version,'parent_pid':os.getpid(),'restart':True},ensure_ascii=False,indent=2),encoding='utf8')
        return plan
    except Exception:
        package.unlink(missing_ok=True)
        raise


def wait_for_parent(pid, timeout=90):
    if type(pid) is not int or pid <= 0 or pid == os.getpid(): raise UpdateError('更新进程参数无效。')
    if os.name != 'nt': return
    from ctypes import wintypes
    api = ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]; api.OpenProcess.restype=wintypes.HANDLE
    api.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]; api.WaitForSingleObject.restype=wintypes.DWORD
    api.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=api.OpenProcess(0x00100000,False,pid)
    if not handle:
        if ctypes.get_last_error() == 87: return
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if api.WaitForSingleObject(handle,timeout*1000) != 0: raise UpdateError('启动器未能及时退出，请关闭后重新安装更新。')
    finally: api.CloseHandle(handle)


def apply_update(plan_path, wait=wait_for_parent, restart=None):
    """Run from the staged executable; rollback all app items on replacement failure."""
    plan_path = Path(plan_path).resolve()
    plan = json.loads(plan_path.read_text(encoding='utf8'))
    root = Path(plan['root']).resolve(); stage = Path(plan['stage']).resolve(); work = plan_path.parent
    updates = root/'data'/'updates'
    if work.parent != updates or stage != work/'staging' or not re.fullmatch(r'[0-9a-f]{32}',work.name):
        raise UpdateError('安装计划不在当前启动器的更新目录内。')
    verify_payload(stage,plan['version'])
    prepared=child(work,'prepared'); backup=child(work,'backup')
    if prepared.exists() or backup.exists(): raise UpdateError('这个安装计划已使用，请重新下载。')
    wait(plan['parent_pid'])
    lock = updates/'install.lock'
    with lock.open('x',encoding='utf8') as output: output.write(str(os.getpid()))
    moved = []; installed = []
    result_path=root/'data'/'update-result.json'
    try:
        shutil.copytree(stage,prepared)
        verify_payload(prepared,plan['version']); backup.mkdir()
        names=sorted(p.name for p in prepared.iterdir())
        for name in names:
            if name not in DIRECTORIES | ROOT_FILES: raise UpdateError('更新顶层目录无效。')
            target=child(root,name); source=child(prepared,name); old=child(backup,name)
            if target.exists():
                target.rename(old); moved.append(name)
            source.rename(target); installed.append(name)
        result={'ok':True,'version':plan['version'],'backup':str(backup)}
    except Exception as exc:
        rollback_errors=[]
        for name in reversed(installed):
            try: child(root,name).rename(child(prepared,name))
            except OSError as error: rollback_errors.append(str(error))
        for name in reversed(moved):
            try: child(backup,name).rename(child(root,name))
            except OSError as error: rollback_errors.append(str(error))
        result={'ok':False,'version':plan['version'],'error':str(exc),'rollback_errors':rollback_errors,'backup':str(backup)}
    finally:
        lock.unlink(missing_ok=True)
    result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    if plan.get('restart') and (root/EXE).is_file():
        (restart or (lambda exe: subprocess.Popen([str(exe)],cwd=exe.parent)))(root/EXE)
    return result


def launch_installer(plan_path):
    plan=json.loads(Path(plan_path).read_text(encoding='utf8'))
    stage=Path(plan['stage']); verify_payload(stage,plan['version'])
    return subprocess.Popen([str(stage/EXE),'--apply-update',str(Path(plan_path).resolve())],cwd=stage,
                            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
