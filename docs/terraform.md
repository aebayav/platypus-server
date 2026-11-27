# Zero-Touch Cloud Provisioning (OpenTofu / Terraform)

`infra/terraform/` contains ready-to-apply Infrastructure-as-Code stacks for **Hetzner Cloud** (`hcloud`) and **DigitalOcean** (`digitalocean`). Both render a shared Cloud-Init config (`infra/terraform/cloud-init/user-data.yml.tftpl`) that:

1. Creates a non-root sudo user with your SSH public key.
2. Installs Docker Engine and runs `bootstrap.sh` with `PLATYPUS_TARGET=vps` (SSH hardening, UFW, fail2ban, and `platypus` CLI).
3. Optionally seeds `/etc/platypus/server.yml` and runs `platypus apply -f /etc/platypus/server.yml` on first boot.

## Usage (OpenTofu or Terraform)

```bash
cd infra/terraform/hcloud   # or infra/terraform/digitalocean
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars with your API token and SSH public key

tofu init                   # or: terraform init
tofu plan
tofu apply
```

Once complete, inspect Cloud-Init progress or open an SSH tunnel to the dashboard:

```bash
$(tofu output -raw ssh_command) -- sudo cloud-init status --wait
$(tofu output -raw dashboard_tunnel_command)
```
