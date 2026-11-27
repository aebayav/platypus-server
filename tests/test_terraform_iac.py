"""Structural and Cloud-Init rendering tests for OpenTofu / Terraform IaC."""

from pathlib import Path
import yaml


def test_cloud_init_template_renders_valid_cloud_config():
    tpl_path = Path("infra/terraform/cloud-init/user-data.yml.tftpl")
    assert tpl_path.is_file()
    raw = tpl_path.read_text(encoding="utf-8")
    assert raw.startswith("#cloud-config")
    assert "bootstrap.sh" in raw
    assert "platypus apply" in raw

    # Substitute Terraform template placeholders and verify resulting YAML parses
    rendered = (
        raw.replace("${admin_user}", "platypusadmin")
        .replace("${ssh_public_key}", "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItest user@host")
        .replace("${platypus_env}", "prod")
        .replace("${platypus_target}", "vps")
        .replace("${server_spec_b64}", "YXBpVmVyc2lvbjogcGxhdHlwdXMvdjEKbW9kdWxlczogfAo=")
    )
    parsed = yaml.safe_load(rendered)
    assert isinstance(parsed, dict)
    assert "users" in parsed
    assert "runcmd" in parsed


def test_hcloud_and_digitalocean_stacks_define_compute_firewall_and_outputs():
    for provider, resource_kw, fw_kw in (
        ("hcloud", "hcloud_server", "hcloud_firewall"),
        ("digitalocean", "digitalocean_droplet", "digitalocean_firewall"),
    ):
        base = Path("infra/terraform") / provider
        for fname in ("versions.tf", "variables.tf", "main.tf", "outputs.tf", "terraform.tfvars.example"):
            assert (base / fname).is_file(), f"missing {base / fname}"

        main_tf = (base / "main.tf").read_text(encoding="utf-8")
        assert resource_kw in main_tf
        assert fw_kw in main_tf
        assert "user-data.yml.tftpl" in main_tf

        outputs_tf = (base / "outputs.tf").read_text(encoding="utf-8")
        assert "ipv4_address" in outputs_tf
        assert "ssh_command" in outputs_tf

    assert Path("docs/terraform.md").is_file()
