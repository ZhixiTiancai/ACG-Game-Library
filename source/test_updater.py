import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

from acg_core import VERSION
from release_tools import build_release
from updater import (Release,UpdateError,Cancelled,EXE,MANIFEST,REPOSITORY,parse_release,
    check_latest,download_release,extract_package,verify_payload,file_hash,apply_update,request_url,version_tuple)


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.base=Path(self.temp.name).resolve()
        self.built=self.base/'built'; self.built.mkdir(); (self.built/EXE).write_bytes(b'MZ-new-version')
        (self.built/'_internal').mkdir(); (self.built/'_internal'/'runtime.dll').write_bytes(b'new runtime')
        self.project=self.base/'project'; self.project.mkdir()
        (self.project/'source').mkdir(); (self.project/'source'/'app.py').write_text('new source')
        (self.project/'README.md').write_text('public readme')
        (self.project/EXE).write_bytes(b'old developer executable: must not be packaged')
        for name in ['data','Library']:
            (self.project/name).mkdir(); (self.project/name/'private.txt').write_text('private')
        self.package,self.checksum=build_release(self.built,self.base/'release',self.project)
        self.root=self.base/'installed'; self.root.mkdir(); (self.root/EXE).write_bytes(b'old app')
        (self.root/'_internal').mkdir(); (self.root/'_internal'/'old.dll').write_bytes(b'old runtime')
        (self.root/'data').mkdir(); (self.root/'data'/'settings.json').write_text('keep settings')
        (self.root/'Library').mkdir(); (self.root/'Library'/'user-mod.ini').write_text('keep mod')

    def tearDown(self): self.temp.cleanup()

    def release(self):
        return Release(VERSION,'https://github.com/'+REPOSITORY+'/releases/tag/v'+VERSION,
            self.package.name,'https://github.com/'+REPOSITORY+'/releases/download/v'+VERSION+'/'+self.package.name,
            self.package.stat().st_size,file_hash(self.package),'','notes')

    def plan(self):
        with patch('updater.request_url',return_value=io.BytesIO(self.package.read_bytes())):
            plan=download_release(self.release(),self.root)
        data=json.loads(plan.read_text(encoding='utf8')); data['restart']=False
        plan.write_text(json.dumps(data),encoding='utf8')
        return plan,data

    def test_clean_release_and_integrity(self):
        with zipfile.ZipFile(self.package) as archive:
            self.assertFalse(any('/data/' in n or '/Library/' in n for n in archive.namelist()))
            self.assertEqual(archive.read('ACG Game Library/'+EXE),b'MZ-new-version')
        stage=extract_package(self.package,self.base/'stage',VERSION)
        verify_payload(stage,VERSION)
        (stage/'_internal'/'runtime.dll').write_bytes(b'tampered')
        with self.assertRaises(UpdateError): verify_payload(stage,VERSION)

    def test_release_metadata_versions_and_missing_assets(self):
        asset={'name':self.package.name,'size':self.package.stat().st_size,'digest':'sha256:'+file_hash(self.package),'browser_download_url':self.release().download_url}
        data={'tag_name':'v'+VERSION,'assets':[asset],'body':'notes'}
        self.assertEqual(parse_release(data).version,VERSION)
        self.assertGreater(version_tuple('v0.10.0'),version_tuple('0.9.9'))
        for value in ['0.7','latest','v1.0.0-beta']:
            with self.assertRaises(UpdateError): version_tuple(value)
        for changed in [dict(data,assets=[]),dict(data,prerelease=True),dict(data,assets=[dict(asset,digest='')])]:
            with self.assertRaises(UpdateError): parse_release(changed)

    def test_unpublished_release_network_failure_and_url_scope(self):
        with patch('updater.request_url',side_effect=urllib.error.HTTPError('url',404,'missing',{},None)):
            self.assertIsNone(check_latest())
        with patch('updater.request_url',side_effect=urllib.error.URLError('offline')):
            with self.assertRaises(UpdateError): check_latest()
        for url in ['http://github.com/'+REPOSITORY+'/releases/download/v1/a.zip','https://evil.example/a.zip','https://github.com/another/repo/releases/download/v1/a.zip']:
            with self.assertRaises(UpdateError): request_url(url)

    def test_malicious_archives_and_hash_mismatch_never_install(self):
        for index,path in enumerate(['ACG Game Library/../outside.txt','ACG Game Library/data/settings.json','ACG Game Library/source/a.ini:bad']):
            archive=self.base/f'bad{index}.zip'
            with zipfile.ZipFile(archive,'w') as output: output.writestr(path,b'bad')
            with self.assertRaises(UpdateError): extract_package(archive,self.base/f'bad-stage{index}',VERSION)
        bad=self.release().__dict__.copy(); bad['sha256']='0'*64
        with patch('updater.request_url',return_value=io.BytesIO(self.package.read_bytes())):
            with self.assertRaises(UpdateError): download_release(Release(**bad),self.root)
        with patch('updater.request_url',return_value=io.BytesIO(self.package.read_bytes())):
            with self.assertRaises(Cancelled): download_release(self.release(),self.root,cancelled=lambda:True)
        self.assertEqual((self.root/EXE).read_bytes(),b'old app')

    def test_app_update_retains_user_data_and_backups(self):
        plan,data=self.plan()
        result=apply_update(plan,wait=lambda pid:None)
        self.assertTrue(result['ok']); self.assertEqual((self.root/EXE).read_bytes(),b'MZ-new-version')
        self.assertFalse((self.root/'_internal'/'old.dll').exists())
        self.assertEqual((Path(result['backup'])/EXE).read_bytes(),b'old app')
        self.assertEqual((self.root/'data'/'settings.json').read_text(),'keep settings')
        self.assertEqual((self.root/'Library'/'user-mod.ini').read_text(),'keep mod')

    def test_failed_replacement_rolls_back_original_program(self):
        plan,data=self.plan(); original=Path.rename; failed=False
        def rename(path,target):
            nonlocal failed
            if path == plan.parent/'prepared'/'source' and not failed:
                failed=True; raise OSError('simulated locked file')
            return original(path,target)
        with patch.object(Path,'rename',rename): result=apply_update(plan,wait=lambda pid:None)
        self.assertFalse(result['ok']); self.assertFalse(result['rollback_errors'])
        self.assertEqual((self.root/EXE).read_bytes(),b'old app')
        self.assertEqual((self.root/'_internal'/'old.dll').read_bytes(),b'old runtime')
        self.assertFalse((self.root/'source').exists()); self.assertFalse((self.root/MANIFEST).exists())
        self.assertEqual((self.root/'Library'/'user-mod.ini').read_text(),'keep mod')


if __name__ == '__main__': unittest.main(verbosity=2)
