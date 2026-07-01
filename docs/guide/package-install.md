# 安装与打包

## 用户安装

从 [GitHub Releases](https://github.com/MzKyle/DataScope-Studio/releases) 下载对应平台
的安装包。正式安装包已包含 Tauri 桌面端、FastAPI、本地 Python runtime、
DataScope Python 包和 Rerun，用户无需提前安装开发环境。

| 平台 | 发布产物 |
| --- | --- |
| Windows 10/11 x64 | `DataScope-Studio-v0.3.1-windows-x86_64-setup.exe` |
| macOS Apple Silicon | `DataScope-Studio-v0.3.1-macos-aarch64.dmg` |
| macOS Intel | `DataScope-Studio-v0.3.1-macos-x86_64.dmg` |
| Debian / Ubuntu x64 | `DataScope-Studio-v0.3.1-linux-amd64.deb` |
| 其他 Linux x64 | `DataScope-Studio-v0.3.1-linux-x86_64.AppImage` |

安装后从系统应用列表启动 **DataScope Studio**。桌面进程会选择空闲的 localhost
端口并启动内置 API。

## 未签名预发布包

`v0.3.1` 是未签名的 Prerelease。仅从本仓库 Release 页面下载，并可使用同一
Release 中的 `SHA256SUMS.txt` 校验文件。

### Windows

运行 `-setup.exe`。如果 SmartScreen 拦截，确认下载来源后选择“更多信息”与
“仍要运行”。NSIS 安装器按当前用户安装，不要求系统级安装权限；缺少 WebView2
时会使用安装包内置的 bootstrapper。

### macOS

打开 `.dmg` 并将应用拖入“应用程序”。首次运行时按住 Control 点击应用，选择
“打开”并确认；也可以进入“系统设置 > 隐私与安全性”允许打开。

Apple Silicon 使用 `aarch64` 包，Intel Mac 使用 `x86_64` 包。

### Linux

Debian / Ubuntu：

```bash
sudo apt install ./DataScope-Studio-v0.3.1-linux-amd64.deb
```

AppImage：

```bash
chmod +x DataScope-Studio-v0.3.1-linux-x86_64.AppImage
./DataScope-Studio-v0.3.1-linux-x86_64.AppImage
```

## 本地构建安装包

本地构建需要 Python 3.10+、Node.js 20.19+、Rust stable 和当前平台的 Tauri
系统依赖：

```bash
cd apps/desktop
npm install
npm run runtime:build
npm run tauri:build
```

`tauri:build` 按宿主系统选择目标：

- Linux：`.deb` 和 `.AppImage`
- Windows：NSIS `-setup.exe`
- macOS：`.dmg`

也可以显式使用：

```bash
npm run package:linux
npm run package:windows
npm run package:macos
```

Linux 本机打包完成后，产物默认位于：

```text
apps/desktop/src-tauri/target/release/bundle/deb/
apps/desktop/src-tauri/target/release/bundle/appimage/
```

本机安装刚生成的 Debian 包可以执行：

```bash
sudo apt install "./src-tauri/target/release/bundle/deb/DataScope Studio_0.3.1_amd64.deb"
```

安装后可通过系统应用列表启动 **DataScope Studio**，也可以用 `dpkg -L
data-scope-studio` 查看安装路径。AppImage 不需要安装，添加执行权限后直接运行。

`runtime:build` 会从 `astral-sh/python-build-standalone` 下载当前平台的独立
CPython，并在 `apps/desktop/src-tauri/resources/datascope-runtime/` 生成：

- `python/`
- `runtime-manifest.json`
- `THIRD_PARTY_NOTICES.md`

这些生成内容不会提交到 Git。

## 开发用 Runtime

快速验证资源路径时，可以使用当前 Python 环境：

```bash
cd apps/desktop
npm run runtime:build:dev
```

开发 runtime 不保证能够复制到其他机器。公开安装包必须使用 `runtime:build`。

## 发布流程

根目录 `VERSION` 是产品版本基准。创建版本标签前执行：

```bash
python packaging/release/check_version.py --tag v0.3.1
```

推送 `v*` 标签后，GitHub Actions 会先运行测试，再构建 Linux x64、Windows x64、
macOS Apple Silicon 和 macOS Intel 安装包。全部构建成功后才会创建公开
Prerelease，并生成 `SHA256SUMS.txt`。
