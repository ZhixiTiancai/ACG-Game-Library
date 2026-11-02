from pathlib import Path
import sys
import webbrowser

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QFrame,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QCheckBox,QProgressBar

from acg_core import VERSION
from updater import check_latest,download_release,launch_installer,version_tuple,RELEASES_URL,REPOSITORY,Cancelled


class UpdateWorker(QThread):
    checked=Signal(object)
    ready=Signal(str)
    failed=Signal(str)
    progress=Signal(int)

    def __init__(self,root,release=None,parent=None):
        super().__init__(parent); self.root,self.release=root,release

    def run(self):
        try:
            if self.release is None: self.checked.emit(check_latest())
            else:
                plan=download_release(self.release,self.root,self.progress.emit,self.isInterruptionRequested)
                self.ready.emit(str(plan))
        except Cancelled as exc: self.failed.emit(str(exc))
        except Exception as exc: self.failed.emit(f'更新未完成：{exc}')


class UpdatePanel(QFrame):
    message=Signal(str,bool)
    installing=Signal()

    def __init__(self,settings,persist,parent=None):
        super().__init__(parent); self.setObjectName('panel')
        self.settings,self.persist=settings,persist
        self.worker=None; self.release=None; self.plan=None; self.automatic=False
        layout=QVBoxLayout(self); layout.setContentsMargins(24,20,24,22); layout.setSpacing(12)
        row=QHBoxLayout(); title=QLabel('软件更新'); title.setObjectName('sectionTitle'); row.addWidget(title); row.addStretch()
        self.check_button=QPushButton('检查更新'); self.check_button.clicked.connect(lambda:self.start_check()); row.addWidget(self.check_button); layout.addLayout(row)
        current=QLabel(f'当前版本  v{VERSION}  ·  Windows x64 便携版'); current.setObjectName('muted'); layout.addWidget(current)
        self.status=QLabel('点击检查更新，从 GitHub Releases 获取正式版本。'); self.status.setObjectName('muted')
        self.status.setTextFormat(Qt.TextFormat.PlainText); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.notes=QLabel(); self.notes.setTextFormat(Qt.TextFormat.PlainText); self.notes.setWordWrap(True); self.notes.setObjectName('tiny'); self.notes.hide(); layout.addWidget(self.notes)
        self.progress=QProgressBar(); self.progress.setRange(0,100); self.progress.hide(); layout.addWidget(self.progress)
        controls=QHBoxLayout()
        self.auto=QCheckBox('启动时自动检查更新'); self.auto.setChecked(settings.values['check_updates_on_start']); self.auto.toggled.connect(self.set_auto)
        controls.addWidget(self.auto); controls.addStretch()
        release_page=QPushButton('发行页面'); release_page.clicked.connect(lambda:webbrowser.open(RELEASES_URL)); controls.addWidget(release_page)
        self.cancel_button=QPushButton('取消下载'); self.cancel_button.clicked.connect(self.cancel); self.cancel_button.hide(); controls.addWidget(self.cancel_button)
        self.action_button=QPushButton('下载更新'); self.action_button.setObjectName('primary'); self.action_button.setEnabled(False)
        self.action_button.clicked.connect(self.perform_action); controls.addWidget(self.action_button); layout.addLayout(controls)
        source=QLabel(f'更新来源：{REPOSITORY} · 更新保留本地 MOD、分类、设置和背景。'); source.setObjectName('tiny'); source.setWordWrap(True); layout.addWidget(source)

    def set_auto(self,value):
        previous=self.settings.values['check_updates_on_start']; self.settings.values['check_updates_on_start']=value
        if not self.persist():
            self.settings.values['check_updates_on_start']=previous
            self.auto.blockSignals(True); self.auto.setChecked(previous); self.auto.blockSignals(False)

    def busy(self): return bool(self.worker and self.worker.isRunning())

    def start_worker(self,release=None):
        self.worker=UpdateWorker(self.settings.root,release,self)
        self.worker.checked.connect(self.checked); self.worker.ready.connect(self.downloaded)
        self.worker.failed.connect(self.failed); self.worker.progress.connect(self.progress.setValue)
        self.worker.finished.connect(self.finished)
        self.check_button.setEnabled(False); self.action_button.setEnabled(False)
        self.cancel_button.setVisible(release is not None)
        self.worker.start()

    def start_check(self,automatic=False):
        if self.busy() or self.plan: return
        self.automatic=automatic; self.release=None
        self.status.setText('正在检查 GitHub 正式发行版…'); self.notes.hide(); self.progress.hide()
        self.start_worker()

    def checked(self,release):
        if release is None:
            self.status.setText('仓库暂未发布正式版本，请稍后再试。')
        elif version_tuple(release.version) <= version_tuple(VERSION):
            self.status.setText(f'当前已是最新版本：v{VERSION}。')
            if not self.automatic: self.message.emit(f'当前已是最新版本 v{VERSION}。',False)
        else:
            self.release=release
            self.status.setText(f'发现新版本 v{release.version}  ·  {release.size/1024**2:.1f} MB')
            self.notes.setText(release.notes[:1200]); self.notes.setVisible(bool(release.notes))
            self.message.emit(f'发现新版本 v{release.version}，可在设置中下载更新。',False)

    def perform_action(self):
        if self.busy(): return
        if self.plan:
            if not getattr(sys,'frozen',False):
                self.message.emit('源码运行时请通过发行包更新；安装并重启功能用于 EXE 便携版。',True); return
            try:
                launch_installer(self.plan); self.installing.emit()
            except Exception as exc: self.failed(f'无法启动更新安装：{exc}')
        elif self.release:
            self.status.setText(f'正在下载 v{self.release.version}，完成后校验 SHA-256…')
            self.progress.setValue(0); self.progress.show(); self.start_worker(self.release)

    def downloaded(self,plan):
        self.plan=Path(plan); self.status.setText('下载及文件校验完成。点击“安装并重启”完成更新。')
        self.action_button.setText('安装并重启'); self.progress.setValue(100)

    def failed(self,message):
        self.status.setText(message)
        if not self.automatic: self.message.emit(message,True)

    def finished(self):
        self.check_button.setEnabled(not self.plan)
        self.action_button.setEnabled(bool(self.plan or self.release))
        self.cancel_button.hide()

    def cancel(self):
        if self.busy(): self.worker.requestInterruption(); self.status.setText('正在取消下载…')
