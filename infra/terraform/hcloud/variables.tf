variable "hcloud_token" {
  description = "Hetzner Cloud API token"
  type        = string
  sensitive   = true
}

variable "server_name" {
  description = "Hostname of the Platypus VPS"
  type        = string
  default     = "platypus-vps"
}

variable "server_type" {
  description = "Hetzner server plan (e.g. cx22, cpx21, cax11)"
  type        = string
  default     = "cx22"
}

variable "location" {
  description = "Hetzner datacenter location"
  type        = string
  default     = "nbg1"
}

variable "image" {
  description = "Base OS image"
  type        = string
  default     = "debian-12"
}

variable "admin_user" {
  description = "Non-root sudo user provisioned via cloud-init"
  type        = string
  default     = "platypusadmin"
}

variable "ssh_public_key" {
  description = "SSH public key string authorized for root and admin_user"
  type        = string
}

variable "platypus_env" {
  description = "Ansible environment passed to bootstrap.sh (prod or dev)"
  type        = string
  default     = "prod"
}

variable "server_spec_path" {
  description = "Optional path to a declarative server.yml applied on first boot"
  type        = string
  default     = ""
}
