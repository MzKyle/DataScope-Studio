# Security Policy

DataScope Studio is a local-first desktop and API application. It does not upload user data by
default, but it does read local files, copy datasets into a workspace, run local adapters, and
launch external viewer processes.

## Supported Versions

Security fixes target the current `main` branch until formal release branches are introduced.

## Reporting a Vulnerability

Please report security issues privately through the repository owner's preferred contact channel.
Do not open a public issue with exploit details.

Include:

- Affected version or commit
- Operating system
- Reproduction steps
- Impact and affected data paths
- Whether plugins, templates, or external datasets are involved

## Local Plugin Guidance

The plugin system is designed for trusted local plugins. Review plugin manifests and entrypoints
before installing them, and avoid running plugins from unknown sources.
