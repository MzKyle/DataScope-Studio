# DataScope Studio

[English](README.md) | [简体中文](README.zh-CN.md)

![DataScope Studio](docs/assets/cover.png)

DataScope Studio turns robotics, industrial, and sensor datasets into interactive
[Rerun](https://rerun.io/) visualizations. Import local data, review the automatically
generated mapping, build a recording, and open it in Rerun without writing a custom
visualization script.

[Download DataScope Studio](https://github.com/MzKyle/DataScope-Studio/releases) |
[Read the documentation](docs/README.md)

## What You Can Do

- Inspect heterogeneous data in one repeatable workflow.
- Automatically map timestamps, scalar values, states, logs, images, detections, and point clouds.
- Generate reusable Rerun `.rrd` recordings and `.rbl` blueprints.
- Organize projects, recordings, jobs, tags, parameters, and query exports locally.
- Search common conditions such as errors, low battery, detection failures, and state duration.
- Export and reopen complete DataScope project packages.

## Supported Data

| Source | Examples |
| --- | --- |
| Tables and logs | CSV, JSONL |
| Computer vision | Image folders with detection sidecars |
| Point clouds | PLY, PCD, NPY, NPZ files or frame directories |
| Robotics recordings | MCAP and ROS2 DB3 bags, including split bag directories |

DataScope is local-first. Source data, mappings, recordings, and the SQLite catalog remain
in your local workspace unless you explicitly export a project package.

## Install

Download the installer for your computer from
[GitHub Releases](https://github.com/MzKyle/DataScope-Studio/releases).

| System | Download |
| --- | --- |
| Windows 10/11 x64 | `DataScope-Studio-v0.2.0-windows-x86_64-setup.exe` |
| macOS Apple Silicon | `DataScope-Studio-v0.2.0-macos-aarch64.dmg` |
| macOS Intel | `DataScope-Studio-v0.2.0-macos-x86_64.dmg` |
| Debian/Ubuntu x64 | `DataScope-Studio-v0.2.0-linux-amd64.deb` |
| Other Linux x64 | `DataScope-Studio-v0.2.0-linux-x86_64.AppImage` |

The installer includes the desktop application, local API, Python runtime, and Rerun.
Python, Node.js, npm, and Rerun do not need to be installed separately.

The `v0.2.0` packages are unsigned prerelease builds:

- **Windows:** if SmartScreen appears, choose **More info** and then **Run anyway** after
  confirming the installer came from this repository.
- **macOS:** drag DataScope Studio to Applications. On first launch, Control-click the app,
  choose **Open**, and confirm. You can also allow it under **System Settings > Privacy &
  Security**.
- **Linux AppImage:** make it executable before launching:

```bash
chmod +x DataScope-Studio-v0.2.0-linux-x86_64.AppImage
./DataScope-Studio-v0.2.0-linux-x86_64.AppImage
```

For the Debian package:

```bash
sudo apt install ./DataScope-Studio-v0.2.0-linux-amd64.deb
```

## First Visualization

1. Open DataScope Studio and create or select a project.
2. Choose a CSV, JSONL, image folder, point cloud, MCAP, or ROS2 DB3 source.
3. Select **Import & Auto Map**.
4. Review the detected streams and preview. Correct the time field or semantic mapping if needed.
5. Select **Validate Mapping**, then **Confirm Mapping**.
6. Select **Build .rrd + .rbl**.
7. Select **Open in Rerun** to inspect the result.

Projects are stored under `~/.datascope-studio` by default. Existing project packages can
be reopened from **Open Package** on the dashboard.

## Documentation

- [Installation and packaging](docs/guide/package-install.md)
- [Import and conversion workflow](docs/workflow/import-convert.md)
- [Troubleshooting](docs/faq/troubleshooting.md)
- [Developer setup](docs/guide/run-app.md)
- [Architecture and API documentation](docs/architecture/README.md)

## License

DataScope Studio is licensed under the [Apache License 2.0](LICENSE).
