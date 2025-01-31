variable "gke_username" {
  description = "gke username"
}

variable "gke_password" {
  description = "gke password"
}

variable "cluster_name" {
  description = "Name of the Cluster"
}

variable "gke_num_nodes" {
  description = "number of gke nodes"
  default     = 1
}

variable "registry_server" {
  default = "europe-west9-docker.pkg.dev"
}

variable "registry_email" {
  default = "goli.sateesh@example.com"
}

variable "gcs_key_file" {
  description = "Path to the GCS service account key file"
  #default = "${path.module}/terraform-key.json"
}


# GKE cluster
data "google_container_engine_versions" "gke_version" {
  location       = var.region
  version_prefix = "1.30.6-gke.1125000"
}

resource "google_container_cluster" "primary" {
  name     = "${var.cluster_name}-gke"
  location = var.region

  # Disable deletion protection to false
  deletion_protection = false

  remove_default_node_pool = true
  initial_node_count       = 1

  network    = google_compute_network.vpc.name
  subnetwork = google_compute_subnetwork.subnet.name
}

# Separately Managed Node Pool 
resource "google_container_node_pool" "test_futurandco_nodes" {
  name     = "test-futurandco-nodepool"
  location = var.region
  cluster  = google_container_cluster.primary.name


  version = "1.30.6-gke.1125000"
  #data.google_container_engine_versions.gke_version.release_channel_latest_version["STABLE"]
  node_count = var.gke_num_nodes
  #node_locations = ["us-west4-a", "us-west4-b"]

  node_config {
    service_account = "service-account-550@ia-generation-5.iam.gserviceaccount.com"
    disk_size_gb    = 40
    disk_type       = "pd-standard"
    oauth_scopes = [
      "https://www.googleapis.com/auth/logging.write",
      "https://www.googleapis.com/auth/monitoring",
      "https://www.googleapis.com/auth/cloud-platform"
    ]

    labels = {
      env = var.cluster_name
    }

    preemptible  = true
    machine_type = "n1-standard-1"
    tags         = ["gke-node", "${var.cluster_name}-gke"]
    metadata = {
      disable-legacy-endpoints = "true"
    }

  }

}

resource "kubernetes_secret" "gcs_credentials" {
  metadata {
    name      = "gcs-credentials"
    namespace = "default"
  }

  data = {
    "key.json" = filebase64(var.gcs_key_file)
  }

  type = "Opaque"
}



# Get the client config for authentication
data "google_client_config" "default" {}

# Kubernetes provider configuration to interact with the GKE cluster
provider "kubernetes" {
  host                   = google_container_cluster.primary.endpoint
  token                  = data.google_client_config.default.access_token
  cluster_ca_certificate = base64decode(google_container_cluster.primary.master_auth.0.cluster_ca_certificate)
}

resource "kubernetes_secret" "gcr-secret" {
  metadata {
    name      = "gcr-secret"
    namespace = "default" # Set your desired namespace
  }

  type = "kubernetes.io/dockerconfigjson"

  data = {
    ".dockerconfigjson" = jsonencode({
      auths = {
        "${var.registry_server}" = {
          "username" = "_json_key"                                                            # For GCR or Artifact Registry, username is "_json_key"
          "password" = file("${path.module}/terraform-key.json")                              # Fetch the service account key from local file
          "email"    = var.registry_email                                                     # Your registry email
          "auth"     = base64encode("_json_key:${file("${path.module}/terraform-key.json")}") # Base64 encoded credentials
        }
      }
    })
  }
  depends_on = [google_container_cluster.primary]
}


