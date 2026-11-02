"""Create a clean portable release. Never distribute a developer's Library/data."""
import argparse
import json
from pathlib import Path
import zipfile

from acg_core import VERSION
from updater import APP_ID,EXE,MANIFEST,ROOT_FILES,DIRECTORIES,file_hash,verify_payload


def build_release(app_dir,output,project=None):
    app_dir,output=Path(app_dir),Path(output)
    project=Path(project) if project else Path(__file__).resolve().parent.parent
    output.mkdir(parents=True,exist_ok=True)
    files={}
    for base,names in [(app_dir,{EXE,'_internal'}),(project,(DIRECTORIES-{'_internal'}) | (ROOT_FILES-{EXE,MANIFEST}))]:
        for name in names:
            path=base/name
            if path.is_file(): files[name]=path
            elif path.is_dir():
                for file in path.rglob('*'):
                    if file.is_file() and '__pycache__' not in file.parts and file.suffix not in {'.pyc','.pyo'}:
                        files[file.relative_to(base).as_posix()]=file
    if EXE not in files or not any(name.startswith('_internal/') for name in files): raise ValueError('先构建完整的 Windows 便携版。')
    manifest={'schema':1,'app_id':APP_ID,'version':VERSION,'platform':'windows-x64',
              'files':{name:file_hash(path) for name,path in sorted(files.items())}}
    filename=f'ACG-Game-Library-v{VERSION}-windows-x64.zip'
    package=output/filename
    with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,path in sorted(files.items()): archive.write(path,'ACG Game Library/'+name)
        archive.writestr('ACG Game Library/'+MANIFEST,json.dumps(manifest,ensure_ascii=False,indent=2))
    checksum=output/(filename+'.sha256'); checksum.write_text(file_hash(package)+'  '+filename+'\n',encoding='ascii')
    return package,checksum


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--app-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path('release')); parser.add_argument('--tag',default='')
    args=parser.parse_args()
    if args.tag and args.tag != 'v'+VERSION: parser.error('标签必须与 source/acg_core.py 的 VERSION 一致。')
    for path in build_release(args.app_dir,args.output): print(path)
