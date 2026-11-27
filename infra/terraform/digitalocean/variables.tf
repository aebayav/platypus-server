variable "do_token" {
  description = "DigitalOcean personal access token"
  type        = string
  sensitive   = true
}

variable "server_name" {
  description = "Droplet hostname"
  type        = string
  default     = "platypus-vps"
}

variable "size" {
  description = "Droplet size slug"
  type        = string
  default     = "s-2vcpu-2gb"
}

variable "region" {
  description = "DigitalOcean region slug"
  type        = string
  default     = "fra1"
}

variable "image" {
  description = "Base Droplet image slug"
  type        = string
  default     = "debian-12-x64"
}

variable "admin_user" {
  description = "Non-root sudo user provisioned via cloud-init"
  type        = string
  default     = "platypusadmin"
}

variable "ssh_public_key" {
  description = "SSH public key string"
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
