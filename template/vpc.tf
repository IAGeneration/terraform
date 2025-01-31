#variable "project_id" {
#  description = "project id"
#} 

#variable "region" {
#    description = "region"
#}

#provider "google" {
#    project = var.project_id
#    region  = var.region
#}

variable "vpc_name" {
  description = "Name of the VPC network"
}

# VPC
resource "google_compute_network" "vpc" {
  name                    = "${var.vpc_name}-vpc"
  auto_create_subnetworks = "false"
}

# Subnet 
resource "google_compute_subnetwork" "subnet" {
  name          = "${var.vpc_name}-subnet"
  region        = var.region
  network       = google_compute_network.vpc.name
  ip_cidr_range = "10.10.0.0/28"
}

# Firewall 

resource "google_compute_firewall" "allow_http" {
  name    = "${var.vpc_name}-firewall"
  network = "${var.vpc_name}-vpc"

  allow {
    protocol = "tcp"
    ports    = ["80"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["http-server"]
}
