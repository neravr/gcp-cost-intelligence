output "cost_analysis_dataset" {
  value       = google_bigquery_dataset.cost_analysis.dataset_id
  description = "BigQuery dataset for cost analysis results"
}

output "pubsub_topic" {
  value       = google_pubsub_topic.cost_anomalies.name
  description = "Pub/Sub topic for cost anomalies"
}

output "functions_sa_email" {
  value       = google_service_account.functions_sa.email
  description = "Service account email for Cloud Functions"
}

output "scheduler_job" {
  value       = google_cloud_scheduler_job.daily_analysis.name
  description = "Cloud Scheduler job name"
}