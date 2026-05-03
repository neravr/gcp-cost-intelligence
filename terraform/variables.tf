variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  description = "GCP region"
  default     = "us-central1"
}

variable "env" {
  type        = string
  description = "Environment: dev, staging, prod"
  default     = "dev"
}

variable "anthropic_api_key" {
  type        = string
  description = "Anthropic Claude API key"
  sensitive   = true
}

variable "sendgrid_api_key" {
  type        = string
  description = "SendGrid API key for email reports"
  sensitive   = true
}

variable "report_email" {
  type        = string
  description = "Email address to send daily cost reports to"
}

variable "billing_dataset" {
  type        = string
  description = "BigQuery dataset containing billing export"
  default     = "billing_export"
}

variable "billing_table" {
  type        = string
  description = "BigQuery table containing billing export data"
  default     = "gcp_billing_export_v1_XXXXXX_XXXXXX_XXXXXX"
}