terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  backend "gcs" {
    bucket = "gcp-cost-intelligence-tfstate"
    prefix = "terraform/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# BigQuery dataset for cost analysis
resource "google_bigquery_dataset" "cost_analysis" {
  dataset_id  = "cost_analysis"
  location    = "US"
  description = "Cost intelligence analysis results"

  labels = {
    env        = var.env
    managed-by = "terraform"
  }
}

# Pub/Sub topic for anomaly alerts
resource "google_pubsub_topic" "cost_anomalies" {
  name = "cost-anomalies-${var.env}"

  labels = {
    env        = var.env
    managed-by = "terraform"
  }
}

# Pub/Sub subscription
resource "google_pubsub_subscription" "cost_anomalies_sub" {
  name  = "cost-anomalies-sub-${var.env}"
  topic = google_pubsub_topic.cost_anomalies.name

  ack_deadline_seconds = 60
}

# Service account for Cloud Functions
resource "google_service_account" "functions_sa" {
  account_id   = "cost-functions-sa"
  display_name = "Cost Intelligence Functions SA"
}

# IAM roles for service account
resource "google_project_iam_member" "bigquery_reader" {
  project = var.project_id
  role    = "roles/bigquery.dataViewer"
  member  = "serviceAccount:${google_service_account.functions_sa.email}"
}

resource "google_project_iam_member" "bigquery_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.functions_sa.email}"
}

resource "google_project_iam_member" "pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.functions_sa.email}"
}

# Cloud Scheduler job — runs daily at 8am UTC
resource "google_cloud_scheduler_job" "daily_analysis" {
  name      = "daily-cost-analysis"
  schedule  = "0 8 * * *"
  time_zone = "UTC"

  http_target {
    uri         = "https://${var.region}-${var.project_id}.cloudfunctions.net/billing-analyzer"
    http_method = "POST"

    oidc_token {
      service_account_email = google_service_account.functions_sa.email
    }
  }
}