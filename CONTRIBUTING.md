# Contributing to Platypus Server

Contributions — especially new community modules, multi-distro Ansible improvements, and bug fixes — are welcome!

## Adding a New Module

1. Scaffold the module skeleton:
   ```bash
   platypus module init <module-name>
   ```
2. Edit `recipe/modules/<module-name>/template.yml` and `questions.yml` (see [docs/modules.md](docs/modules.md)).
   - Persist container state under `./data` so `platypus dismount` freezes user data without loss.
   - Declare every host port published by `compose_template` inside `ports:`.
   - Route Caddy to `localhost:{answers[web_port]}` rather than internal Docker hostnames.
3. Run the local quality gates:
   ```bash
   platypus module lint
   yamllint .
   pytest -q
   ```

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pip install -r requirements.txt
pytest -q
```
