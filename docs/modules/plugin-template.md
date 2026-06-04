# 插件与模板

插件和模板 registry 是 V1.0 的本地扩展骨架，当前目标是可信本地扩展，不实现远程 marketplace。

## 插件 Manifest

插件使用 `plugin.yaml` 描述：

```yaml
id: example.adapter
name: Example Adapter
version: 0.1.0
min_datascope_version: 1.0.0
entrypoints:
  adapters:
    - module: example_plugin.adapter
      class: ExampleAdapter
permissions:
  filesystem:
    read: true
```

核心会校验 manifest、entrypoint 和权限字段。插件运行仍属于可信本地代码，请只安装来源可信的插件。

## 模板 Registry

内置模板包括：

- `sensor_monitor`
- `cv_detection`
- `robotics_debug`
- `experiment_compare`

本地模板可通过 YAML 安装、启用或禁用。
