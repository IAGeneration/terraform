variable "project_id" {
  description = "The project ID"
}

variable "region" {
  description = "The region for the resources"
}

variable "zone" {
  description = "The zone for the resources"
}

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "6.8.0"
    }
  }
}

provider "google" {
  credentials = file("./terraform-key.json")
  project     = var.project_id
  region      = var.region
  zone        = var.zone
}
