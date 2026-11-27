locals {
  server_spec_b64 = var.server_spec_path != "" ? filebase64(var.server_spec_path) : ""
}

resource "hcloud_ssh_key" "platypus" {
  name       = "${var.server_name}-key"
  public_key = var.ssh_public_key
}

resource "hcloud_firewall" "platypus" {
  name = "${var.server_name}-fw"

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "80"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "443"
    source_ips = ["0.0.0.0/0", "::/0"]
  }
}

resource "hcloud_server" "platypus" {
  name         = var.server_name
  server_type  = var.server_type
  image        = var.image
  location     = var.location
  ssh_keys     = [hcloud_ssh_key.platypus.id]
  firewall_ids = [hcloud_firewall.platypus.id]

  user_data = templatefile("${path.module}/../cloud-init/user-data.yml.tftpl", {
    admin_user       = var.admin_user
    ssh_public_key   = var.ssh_public_key
    platypus_env     = var.platypus_env
    platypus_target  = "vps"
    server_spec_b64  = local.server_spec_b64
  })
}
