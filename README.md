# ACG Game Library

本地 MOD 整理与部署工具，支持 **SRMI / ZZMI / EFMI**，通过设置连接外部 XXMI。

## 下载与使用

从 [Releases 下载 Windows x64 便携版](https://github.com/ZhixiTiancai/ACG-Game-Library/releases/latest)，完整解压 ZIP，双击 `ACG Game Library.exe`。请将 EXE 和 `_internal` 文件夹放在一起，安装位置需允许当前用户写入。

发行包为**空库**，不包含任何 MOD、个人数据或 XXMI。设置中选择已有的 XXMI 路径即可使用。

- 按游戏分类管理本地 MOD，支持 ZIP 导入、文件夹刷新、搜索和收藏。
- 竖向分类列表：未分类置顶，其余按符号、字母、汉字分组排序，中文按拼音排序。
- 同一分类可同时使用多个 MOD，使用/停用通过目录连接部署到外部 XXMI。
- 3:4 封面保存为各模组文件夹内的 `preview.jpg`，支持自动检测和替换。
- 七种低饱和度完整主题、自定义背景和透明度调节，设置自动保存。
- 设置内检查、下载更新，校验后安装并重启，保留 MOD、分类、设置和背景。

详细操作见 [使用说明](使用说明.md)。问题可提交到 [Issues](https://github.com/ZhixiTiancai/ACG-Game-Library/issues)。

## 源码运行与构建

Windows x64，Python 3.12：

```powershell
python -m pip install -r source/requirements.txt
python source/main.py
python -m unittest discover -s source -v
python -m PyInstaller --noconfirm --distpath dist --workpath build "source/ACG Game Library.spec"
python source/release_tools.py --app-dir "dist/ACG Game Library" --output release
```

`release_tools.py` 只收集程序、运行库、源码和说明，自动生成更新清单、Windows ZIP 和 SHA-256 文件；不会打包 `Library`、`data` 或本机设置。

## 发布后续版本

1. 更新 `source/acg_core.py` 中的 `VERSION`、`source/version_info.txt` 和发行说明。
2. 提交代码并推送同版本标签，例如 `v0.7.1`。
3. GitHub Actions 自动测试、构建并发布 ZIP 与校验文件；其他用户在设置中检查更新即可获取。

第三方组件及许可见 [THIRD-PARTY.txt](THIRD-PARTY.txt) 和 `licenses`。
