output "ipv4_address" {
  description = "Public IPv4 address of the provisioned Droplet"
  value       = digitalocean_droplet.platypus.ipv4_address
}

output "ssh_command" {
  description = "SSH login command"
  value       = "ssh ${var.admin_user}@${digitalocean_droplet.platypus.ipv4_address}"
}

output "dashboard_tunnel_command" {
  description = "SSH local port forward to reach the loopback-bound dashboard"
  value       = "ssh -L 5050:127.0.0.1:5050 ${var.admin_user}@${digitalocean_droplet.platypus.ipv4_address}"
}
