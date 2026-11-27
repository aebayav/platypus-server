locals {
  server_spec_b64 = var.server_spec_path != "" ? filebase64(var.server_spec_path) : ""
}

resource "digitalocean_ssh_key" "platypus" {
  name       = "${var.server_name}-key"
  public_key = var.ssh_public_key
}

resource "digitalocean_droplet" "platypus" {
  name     = var.server_name
  size     = var.size
  image    = var.image
  region   = var.region
  ssh_keys = [digitalocean_ssh_key.platypus.fingerprint]

  user_data = templatefile("${path.module}/../cloud-init/user-data.yml.tftpl", {
    admin_user       = var.admin_user
    ssh_public_key   = var.ssh_public_key
    platypus_env     = var.platypus_env
    platypus_target  = "vps"
    server_spec_b64  = local.server_spec_b64
  })
}

resource "digitalocean_firewall" "platypus" {
  name        = "${var.server_name}-fw"
  droplet_ids = [digitalocean_droplet.platypus.id]

  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "80"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "443"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}
