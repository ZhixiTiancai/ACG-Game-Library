"""Per-game categories and metadata. User originals are never renamed or edited."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat
import uuid
import zipfile

from acg_core import GAMES
from deployment import create_link, remove_link, matches_link, is_link
from preview_images import save_portrait

UNCATEGORIZED = 'uncategorized'
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}


class LibraryStore:
    def __init__(self, base: Path):
        self.base = Path(base)
        self.cache = {}
        self.errors = {}

    def game_path(self, game):
        if game not in GAMES:
            raise ValueError('不支持的游戏')
        return self.base / game

    def load(self, game):
        if game in self.cache:
            return self.cache[game]
        data = {'schema': 1, 'categories': [{'id': UNCATEGORIZED, 'name': '未分类'}], 'mods': []}
        path = self.game_path(game) / '.acg-library.json'
        if path.exists():
            try:
                saved = json.loads(path.read_text(encoding='utf8'))
                if not isinstance(saved, dict) or not isinstance(saved.get('categories'), list) or not isinstance(saved.get('mods'), list):
                    raise ValueError('索引结构不正确')
                cats, seen = data['categories'], {UNCATEGORIZED}
                for cat in saved['categories']:
                    if isinstance(cat, dict) and isinstance(cat.get('id'), str) and isinstance(cat.get('name'), str) and cat['id'] not in seen and cat['name'].strip():
                        cats.append({'id': cat['id'], 'name': cat['name']}); seen.add(cat['id'])
                ids = set()
                for mod in saved['mods']:
                    if not isinstance(mod, dict) or not all(isinstance(mod.get(k), str) for k in ['id', 'name', 'folder']):
                        continue
                    if mod['id'] in ids:
                        continue
                    record = {k: mod[k] for k in ['id', 'name', 'folder']}
                    record.update(category_id=mod.get('category_id') if mod.get('category_id') in seen else UNCATEGORIZED,
                                  favorite=mod.get('favorite') is True, preview=mod.get('preview') if isinstance(mod.get('preview'), str) else '')
                    deployment = mod.get('deployment')
                    record['deployment'] = deployment if isinstance(deployment, dict) and all(isinstance(deployment.get(k), str) for k in ['path', 'target']) else None
                    record['portrait_preview'] = mod.get('portrait_preview') is True
                    data['mods'].append(record); ids.add(record['id'])
            except (ValueError, OSError, TypeError) as exc:
                self.errors[game] = f'库索引无法读取，原文件保留：{exc}'
        self.cache[game] = data
        return data

    def save(self, game):
        if game in self.errors:
            raise ValueError(self.errors[game])
        path = self.game_path(game) / '.acg-library.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.json.tmp')
        temp.write_text(json.dumps(self.load(game), ensure_ascii=False, indent=2), encoding='utf8')
        os.replace(temp, path)

    def categories(self, game):
        return copy.deepcopy(self.load(game)['categories'])

    def mods(self, game, category=None, favorites=False, query=''):
        query = query.strip().casefold()
        return [copy.deepcopy(m) for m in self.load(game)['mods']
                if (category is None or m['category_id'] == category)
                and (not favorites or m['favorite']) and (not query or query in m['name'].casefold())]

    def category_name(self, game, category):
        return next((c['name'] for c in self.categories(game) if c['id'] == category), '未分类')

    def add_category(self, game, name):
        name = name.strip()
        if not name or len(name) > 40:
            raise ValueError('分类名称须为 1–40 个字符。')
        if any(c['name'].casefold() == name.casefold() for c in self.categories(game)):
            raise ValueError('这个分类名称已经存在。')
        cat = {'id': uuid.uuid4().hex, 'name': name}
        self.load(game)['categories'].append(cat)
        try:
            self.save(game)
        except Exception:
            self.load(game)['categories'].remove(cat); raise
        return cat

    def get(self, game, mod_id):
        return next((copy.deepcopy(m) for m in self.load(game)['mods'] if m['id'] == mod_id), None)

    def update(self, game, mod_id, **values):
        mod = next((m for m in self.load(game)['mods'] if m['id'] == mod_id), None)
        if mod is None:
            raise ValueError('找不到该模组')
        before = copy.deepcopy(mod)
        if 'name' in values:
            name = str(values['name']).strip()
            if not name or len(name) > 120:
                raise ValueError('名称须为 1–120 个字符。')
            values['name'] = name
        if 'category_id' in values and values['category_id'] not in {c['id'] for c in self.categories(game)}:
            raise ValueError('分类不存在')
        undo = self._rename_folder(game, mod, values['name']) if 'name' in values else None
        for key in ['name', 'category_id', 'preview', 'favorite', 'portrait_preview']:
            if key in values:
                mod[key] = values[key]
        try:
            self.save(game)
        except Exception:
            if undo: undo()
            mod.clear(); mod.update(before); raise
        return copy.deepcopy(mod)

    def absolute(self, game, value):
        path = Path(value)
        return path if path.is_absolute() else self.game_path(game) / path

    def set_preview(self, game, mod_id, source: Path):
        mod = self.get(game, mod_id)
        if not mod:
            raise ValueError('找不到该模组')
        source = Path(source)
        extension = source.suffix.casefold()
        if extension not in IMAGE_EXTENSIONS:
            raise ValueError('不支持的图片格式')
        folder = self._owned_folder(game, mod)
        destination = folder / 'preview.jpg'
        if is_link(destination):
            raise ValueError('preview.jpg 不能是文件链接。')
        temporary = folder / f'.acg-preview-{uuid.uuid4().hex}.jpg'
        previous = destination.read_bytes() if destination.is_file() else None
        try:
            save_portrait(source, temporary)
            os.replace(temporary, destination)
            self.update(game, mod_id, preview=destination.relative_to(self.game_path(game)).as_posix(), portrait_preview=True)
        except Exception:
            if previous is not None: destination.write_bytes(previous)
            else: destination.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)
        # Only known image variants in this owned MOD root are obsolete covers.
        self._clean_preview_variants(folder)
        old = self.absolute(game, mod['preview']) if mod['preview'] else None
        legacy = self.game_path(game) / '.previews'
        if old and old.is_file() and not is_link(old) and old.resolve().parent == legacy.resolve():
            old.unlink()
        self._clean_legacy_previews(game, mod_id)

    def _clean_legacy_previews(self, game, mod_id):
        legacy = self.game_path(game) / '.previews'
        if not legacy.is_dir() or is_link(legacy): return
        used = {self.absolute(game, m['preview']).resolve() for m in self.mods(game) if m['preview']}
        for path in legacy.iterdir():
            if re.fullmatch(re.escape(mod_id) + r'-[0-9a-f]{32}\.(?:png|jpg)', path.name) and path.is_file() and not is_link(path) and path.resolve() not in used:
                path.unlink()
        if not any(legacy.iterdir()): legacy.rmdir()

    @staticmethod
    def _clean_preview_variants(folder):
        for path in folder.iterdir():
            if path != folder / 'preview.jpg' and path.stem.casefold() == 'preview' and path.suffix.casefold() in IMAGE_EXTENSIONS and path.is_file() and not is_link(path):
                path.unlink()

    def import_zip(self, game, source: Path, category=UNCATEGORIZED):
        source = Path(source)
        if category not in {c['id'] for c in self.categories(game)}:
            raise ValueError('分类不存在')
        game_root = self.game_path(game)
        token = uuid.uuid4().hex
        staging = game_root / '.imports' / token
        final = None
        installed = False
        try:
            with zipfile.ZipFile(source) as archive:
                entries = archive.infolist()
                if len(entries) > 50000 or sum(i.file_size for i in entries) > 4 * 1024**3:
                    raise ValueError('压缩包过大：当前支持最多 4 GiB、50000 个文件。')
                normalized = set()
                for item in entries:
                    name = item.filename.replace('\\', '/')
                    parts = Path(name).parts
                    if not name or name.startswith('/') or PureWindowsPath(name).drive or '..' in parts or stat.S_ISLNK(item.external_attr >> 16):
                        raise ValueError('压缩包包含不安全的路径或链接。')
                    # Windows treats trailing dots/spaces and case as equivalent.
                    if any(p.rstrip(' .') != p or ':' in p for p in parts):
                        raise ValueError('压缩包包含不兼容的 Windows 文件名。')
                    key = name.rstrip('/').casefold()
                    if key in normalized:
                        raise ValueError('压缩包包含重复文件路径。')
                    normalized.add(key)
                staging.mkdir(parents=True)
                for item in entries:
                    destination = (staging / item.filename.replace('\\', '/')).resolve()
                    if not destination.is_relative_to(staging.resolve()):
                        raise ValueError('压缩包路径超出导入目录。')
                    if item.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                    else:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(item) as src, destination.open('wb') as dst:
                            shutil.copyfileobj(src, dst)
            ini_files = list(staging.rglob('*.ini'))
            if not ini_files:
                raise ValueError('没有找到 INI 文件，请选择已解压的模型 MOD 对应 ZIP。')
            content = staging
            children = list(content.iterdir())
            while len(children) == 1 and children[0].is_dir():
                content = children[0]; children = list(content.iterdir())
            name = content.name if content != staging else source.stem
            final = self._destination(game, name)
            final.parent.mkdir(parents=True, exist_ok=True)
            content.rename(final)
            installed = True
            preview = self._find_preview(final)
            record = {'id': token, 'name': name, 'folder': final.relative_to(game_root).as_posix(),
                      'preview': preview.relative_to(game_root).as_posix() if preview else '',
                      'favorite': False, 'category_id': category, 'deployment': None, 'portrait_preview': False}
            self.load(game)['mods'].append(record)
            try:
                self.save(game)
                if preview and preview != final / 'preview.jpg':
                    self.set_preview(game, token, preview)
                elif preview: self._clean_preview_variants(final)
            except Exception:
                self.load(game)['mods'].remove(record); raise
            return self.get(game, token)
        except Exception:
            if installed: self._remove_owned(final, game_root)
            raise
        finally:
            self._remove_owned(staging, game_root)

    @staticmethod
    def folder_name(name):
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')[:100].rstrip(' .') or 'MOD'
        if name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *{f'COM{i}' for i in range(1,10)}, *{f'LPT{i}' for i in range(1,10)}}:
            name = '_' + name
        return name

    def _destination(self, game, name, exclude=None):
        parent = self.game_path(game) / 'Mods'
        stem = self.folder_name(name)
        occupied = {p.name.casefold() for p in parent.iterdir() if exclude is None or p != exclude} if parent.exists() else set()
        candidate, index = stem, 2
        while candidate.casefold() in occupied:
            candidate = f'{stem} ({index})'; index += 1
        return parent / candidate

    def _owned_folder(self, game, mod, require_exists=True):
        path = self.absolute(game, mod['folder'])
        parent = (self.game_path(game) / 'Mods').resolve()
        if is_link(path) or path.resolve().parent != parent:
            raise ValueError('模组路径不在 ACG 的独立副本目录中。')
        if require_exists and not path.is_dir():
            raise ValueError('模组文件夹不存在，请重新导入。')
        return path

    def _deployment(self, game, mod):
        value = mod.get('deployment')
        if not value: return None
        link, target = Path(value['path']), Path(value['target'])
        owned = self._owned_folder(game, mod, require_exists=False)
        if link.parent.name.casefold() != 'mods' or link.parent.parent.name.casefold() != game.casefold() or target.resolve() != owned.resolve():
            raise ValueError('部署记录与模组路径不一致，未改动外部文件。')
        return link, target

    def is_enabled(self, game, mod_id):
        mod = self.get(game, mod_id)
        try:
            deployment = self._deployment(game, mod) if mod else None
            return bool(deployment and deployment[1].is_dir() and matches_link(*deployment))
        except (ValueError, OSError):
            return False

    def set_enabled(self, game, mod_id, enabled, target_dir=None):
        mod = next((m for m in self.load(game)['mods'] if m['id'] == mod_id), None)
        if not mod: raise ValueError('找不到该模组')
        source = self._owned_folder(game, mod, require_exists=enabled)
        previous = copy.deepcopy(mod)
        old = self._deployment(game, mod)
        if not enabled:
            if old: remove_link(*old)
            mod['deployment'] = None
            try: self.save(game)
            except Exception:
                mod.clear(); mod.update(previous)
                if old and not os.path.lexists(old[0]) and source.is_dir(): create_link(old[0], source)
                raise
            return self.get(game, mod_id)
        if target_dir is None: raise ValueError('请先在设置中连接外部 XXMI。')
        target_dir = Path(target_dir)
        if target_dir.name.casefold() != 'mods' or target_dir.parent.name != game or not (target_dir.parent/'d3dx.ini').is_file() or is_link(target_dir):
            raise ValueError('XXMI 目标目录或对应游戏组件无效。')
        link = target_dir / source.name
        if old and matches_link(*old):
            if old[0] == link: return self.get(game, mod_id)
            raise ValueError('此模组仍在另一个 XXMI 实例中使用，请先停用后切换。')
        if old and (os.path.lexists(old[0]) or is_link(old[0])):
            raise ValueError('原部署位置被其他内容占用，未覆盖。')
        create_link(link, source)
        mod['deployment'] = {'path': str(link.absolute()), 'target': str(source.resolve())}
        try: self.save(game)
        except Exception:
            remove_link(link, source); mod.clear(); mod.update(previous); raise
        return self.get(game, mod_id)

    def _rename_folder(self, game, mod, name):
        source = self._owned_folder(game, mod)
        destination = self._destination(game, name, exclude=source)
        # No operation is needed for a case-only display-name edit on Windows.
        if source.name.casefold() == destination.name.casefold(): return None
        if source.resolve().parent != destination.resolve().parent:
            raise ValueError('重命名目标超出当前模组库。')
        old = self._deployment(game, mod)
        active = bool(old and matches_link(*old))
        if old and not active and (os.path.lexists(old[0]) or is_link(old[0])):
            raise ValueError('部署位置已被其他内容替换，请先处理该位置。')
        new_link = old[0].parent / destination.name if active else None
        if new_link and (os.path.lexists(new_link) or is_link(new_link)):
            raise ValueError('XXMI 中已有同名内容，请换一个名称。')
        renamed = removed = created = False
        def rollback():
            if created: remove_link(new_link, destination)
            if renamed:
                # Both absolute paths were checked to remain direct children of ACG's Mods folder.
                destination.rename(source)
            if removed: create_link(old[0], source)
        try:
            if active: remove_link(*old); removed = True
            source.rename(destination); renamed = True
            if active: create_link(new_link, destination); created = True
        except Exception:
            rollback(); raise
        if mod['preview']:
            preview = self.absolute(game, mod['preview'])
            try: mod['preview'] = (destination / preview.relative_to(source)).relative_to(self.game_path(game)).as_posix()
            except ValueError: pass
        mod['folder'] = destination.relative_to(self.game_path(game)).as_posix()
        mod['deployment'] = {'path': str(new_link.absolute()), 'target': str(destination.resolve())} if active else None
        return rollback

    def normalize_library(self, game):
        """Upgrade legacy UUID folder names and previews, keeping user choices."""
        self.load(game)
        if game in self.errors: return
        for record in self.mods(game):
            try:
                self.update(game, record['id'], name=record['name'])
                current = self.get(game, record['id'])
                canonical = self._owned_folder(game, current) / 'preview.jpg'
                if current['preview'] and self.absolute(game, current['preview']) != canonical and not canonical.is_file():
                    self.set_preview(game, current['id'], self.absolute(game, current['preview']))
            except (OSError, ValueError) as exc:
                self.errors.setdefault('migration_' + game, str(exc))

    @staticmethod
    def _find_preview(folder):
        canonical = folder / 'preview.jpg'
        if canonical.is_file() and not is_link(canonical): return canonical
        images = [p for p in folder.rglob('*') if p.is_file() and not is_link(p)
                  and p.stem.casefold() in {'preview', 'cover', 'thumbnail'} and p.suffix.casefold() in IMAGE_EXTENSIONS]
        return min(images, key=lambda p: (p.stem.casefold() != 'preview', len(p.parts), str(p).casefold()), default=None)

    @staticmethod
    def _has_ini(folder):
        # Do not walk junctions/symlinks to other libraries or disks.
        for root, dirs, files in os.walk(folder, followlinks=False):
            dirs[:] = [name for name in dirs if not is_link(Path(root) / name)]
            if any(Path(name).suffix.casefold() == '.ini' for name in files): return True
        return False

    def refresh_from_disk(self, game, reload=True):
        """Reconcile this game's independent MOD copies and their on-disk covers."""
        if reload:
            self.cache.pop(game, None); self.errors.pop(game, None)
        data = self.load(game)
        if game in self.errors: raise ValueError(self.errors[game])
        before = copy.deepcopy(data)
        parent = self.game_path(game) / 'Mods'
        if is_link(parent): raise ValueError('模组库 Mods 不能是外部目录连接。')
        folders = sorted((p for p in parent.iterdir() if p.is_dir() and not is_link(p) and not p.name.startswith('.')),
                         key=lambda p: p.name.casefold()) if parent.exists() else []
        by_path = {os.path.normcase(str(p.resolve())): p for p in folders}
        kept, removed, occupied = [], [], set()
        for mod in data['mods']:
            path = self._owned_folder(game, mod, require_exists=False)
            key = os.path.normcase(str(path.resolve()))
            if key in by_path:
                kept.append(mod); occupied.add(key)
            else: removed.append(mod)
        added = 0
        for key, path in by_path.items():
            if key in occupied or not self._has_ini(path): continue
            kept.append({'id': uuid.uuid4().hex, 'name': path.name,
                         'folder': path.relative_to(self.game_path(game)).as_posix(),
                         'category_id': UNCATEGORIZED, 'favorite': False, 'preview': '',
                         'portrait_preview': False, 'deployment': None})
            added += 1
        data['mods'] = kept
        try: self.save(game)
        except Exception:
            self.cache[game] = before; raise
        warnings = []
        for mod in removed:
            try:
                deployment = self._deployment(game, mod)
                if deployment and matches_link(*deployment): remove_link(*deployment)
            except (ValueError, OSError) as exc: warnings.append(str(exc))
        for mod in self.mods(game):
            try:
                folder = self._owned_folder(game, mod)
                canonical = folder / 'preview.jpg'
                if is_link(canonical): raise ValueError(f'{mod["name"]} 的 preview.jpg 是链接，已跳过。')
                if canonical.is_file():
                    value = canonical.relative_to(self.game_path(game)).as_posix()
                    if mod['preview'] != value:
                        self.update(game, mod['id'], preview=value, portrait_preview=True)
                    self._clean_preview_variants(folder)
                    self._clean_legacy_previews(game, mod['id'])
                else:
                    # Legacy ACG images and root-level preview variants migrate once.
                    old = self.absolute(game, mod['preview']) if mod['preview'] else None
                    legacy = self.game_path(game) / '.previews'
                    source = old if old and old.is_file() and old.resolve().parent == legacy.resolve() else None
                    if not source:
                        source = next((p for p in folder.iterdir() if p.is_file() and not is_link(p)
                                       and p.stem.casefold() == 'preview' and p.suffix.casefold() in IMAGE_EXTENSIONS), None)
                    if source: self.set_preview(game, mod['id'], source)
                    elif mod['preview']: self.update(game, mod['id'], preview='', portrait_preview=False)
            except (ValueError, OSError) as exc: warnings.append(str(exc))
        return {'added': added, 'removed': len(removed), 'total': len(kept), 'warnings': warnings}

    @staticmethod
    def _remove_owned(path: Path, root: Path):
        resolved, base = path.resolve(), root.resolve()
        if resolved != base and resolved.is_relative_to(base) and resolved.exists():
            shutil.rmtree(resolved)
