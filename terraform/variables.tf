# ── variables.tf ───────────────────────────────────────────────────────────────
# All sensitive values are supplied via terraform.tfvars (git-ignored) or
# Azure DevOps / GitHub Actions secrets.

variable "subscription_id" {
  description = "Azure Subscription ID"
  type        = string
  sensitive   = true
}

variable "tenant_id" {
  description = "Azure Tenant ID"
  type        = string
  sensitive   = true
}

variable "location" {
  description = "Primary Azure region"
  type        = string
  default     = "East US"
}

variable "environment" {
  description = "Deployment environment (dev / staging / prod)"
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be dev, staging, or prod."
  }
}

variable "project_name" {
  description = "Short project name used as prefix for all resources"
  type        = string
  default     = "finopsai"
}

# ── Container images ───────────────────────────────────────────────────────────

variable "backend_image_tag" {
  description = "Docker image tag for the backend service"
  type        = string
  default     = "latest"
}

variable "frontend_image_tag" {
  description = "Docker image tag for the frontend service"
  type        = string
  default     = "latest"
}

# ── Azure OpenAI ───────────────────────────────────────────────────────────────

variable "azure_openai_endpoint" {
  description = "Azure OpenAI service endpoint URL"
  type        = string
  sensitive   = true
}

variable "azure_openai_api_key" {
  description = "Azure OpenAI API key"
  type        = string
  sensitive   = true
}

variable "azure_openai_deployment" {
  description = "Azure OpenAI chat model deployment name, for example gpt-4o or gpt-4o-mini"
  type        = string
  default     = "gpt-4o"
}

variable "azure_openai_api_version" {
  description = "Azure OpenAI chat completions API version"
  type        = string
  default     = "2024-02-15-preview"
}

# Microsoft Teams Bot Framework

variable "bot_app_id" {
  description = "Microsoft Teams/Azure Bot app registration client ID"
  type        = string
  default     = ""
}

variable "bot_app_secret" {
  description = "Microsoft Teams/Azure Bot app registration client secret"
  type        = string
  default     = ""
  sensitive   = true
}

variable "bot_tenant_id" {
  description = "Microsoft Teams/Azure Bot Entra tenant ID"
  type        = string
  default     = ""
}

variable "bot_validate_auth" {
  description = "Validate Bot Framework bearer tokens in production"
  type        = bool
  default     = true
}

# ── Scaling ────────────────────────────────────────────────────────────────────

variable "backend_min_replicas" {
  description = "Minimum replicas for the backend Container App"
  type        = number
  default     = 1
}

variable "backend_max_replicas" {
  description = "Maximum replicas for the backend Container App"
  type        = number
  default     = 5
}

variable "frontend_min_replicas" {
  type    = number
  default = 1
}

variable "frontend_max_replicas" {
  type    = number
  default = 3
}

# ── Cost Budget ────────────────────────────────────────────────────────────────

variable "monthly_budget_usd" {
  description = "Monthly Azure cost budget in USD for alerting"
  type        = number
  default     = 25000
}

variable "budget_alert_email" {
  description = "Email address for budget alert notifications"
  type        = string
}
