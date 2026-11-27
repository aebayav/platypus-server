# Authoring Platypus Modules

A Platypus module packages a self-contained service stack as two YAML files under `recipe/modules/<name>/`:

- `template.yml` — metadata, declared host port claims, lifecycle hooks, optional Caddy route, and `compose_template`.
- `questions.yml` — interactive setup prompts whose answers render `{answers[<id>]}` placeholders.

## Quickstart

```bash
platypus module init my-app
platypus module lint recipe/modules/my-app
```

## Required `template.yml` Fields

| Key | Type | Description |
|---|---|---|
| `role` | `str` | Must match the module directory name (kebab-case). |
| `version` | `str` | Module schema/template version (e.g. `"1.0"`). |
| `description` | `str` | One-line summary shown in `platypus module list`. |
| `weight` | `main \| companion` | Recommendation label (`companion` for lightweight background services, `main` for primary workloads). |
| `ports` | `list[str]` | Every host port published in `compose_template`, with optional `/tcp` or `/udp` suffix (e.g. `"{answers[web_port]}/tcp"`, `"53/udp"`). |
| `compose_template` | `str` | Docker Compose YAML string binding persistent data under `./data` so `platypus dismount` freezes state cleanly. |

Optional keys:

- `hooks`: `pre_apply`, `post_apply`, `pre_remove`, `post_remove`, `rollback`, `pre_backup`, `post_backup`.
- `caddy`: `{ enabled: true, route: "..." }` — reverse-proxy block targeting `localhost:{answers[web_port]}` (escape literal `{` / `}` as `{{` / `}}`).

## `questions.yml` Schema

```yaml
---
role: my-app
title: "My App"
description: "Short setup description"
questions:
  - id: web_port
    label: "Host HTTP port"
    type: integer          # text | integer | select | confirm
    default: 8085
    validate: "1024-65535" # enforced interactively and at pre-flight
```

## Validation Rules (`platypus module lint`)

1. `role` matches directory name in both files.
2. Every `id` in `questions.yml` is unique; `select` questions declare `choices`; `validate` ranges parse cleanly.
3. Every `{answers[<id>]}` placeholder in `template.yml` exists in `questions.yml`.
4. Every host port published in `compose_template` appears in `ports:`.
