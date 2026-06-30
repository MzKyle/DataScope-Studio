# 插件与模板

插件和模板 registry 是当前版本的本地扩展骨架，目标是可信本地扩展，不实现远程 marketplace。

## 插件 Manifest

插件使用 `plugin.yaml` 描述。下面的示例也保存在
`docs/examples/plugin.yaml`，release sanity check 会直接校验该文件：

```yaml
id: example.adapter
name: Example Adapter
version: 0.1.0
min_datascope_version: 0.3.0
entrypoints:
  adapters:
    example: example_plugin.adapter:ExampleAdapter
permissions:
  - read_files
```

`entrypoints.adapters` 和 `entrypoints.templates` 的值使用 `module:object`
字符串；也可以写成字符串数组，名称会从 object 自动推断。`permissions`
是字符串数组。核心会校验 manifest、entrypoint 和权限字段。插件运行仍属于
可信本地代码，请只安装来源可信的插件。

## 模板 Registry

内置模板包括：

- `sensor_monitor`
- `cv_detection`
- `robotics_debug`
- `experiment_compare`

本地模板可通过 YAML 安装、启用或禁用。示例 manifest 保存在
`docs/examples/template.yaml`。

这里的模板控制 Rerun app id 和 blueprint。字段匹配规则使用独立的
`mapping_template_registry`，可从已确认或草稿 Mapping 创建，并支持 YAML
导入/导出、跨项目应用和项目内双数据源 diff。
