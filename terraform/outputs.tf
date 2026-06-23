# ── outputs.tf ────────────────────────────────────────────────────────────────

output "resource_group_name" {
  description = "Name of the created resource group"
  value       = azurerm_resource_group.main.name
}

output "backend_url" {
  description = "Public HTTPS URL for the FastAPI backend"
  value       = "https://${azurerm_container_app.backend.ingress[0].fqdn}"
}

output "frontend_url" {
  description = "Public HTTPS URL for the React frontend"
  value       = "https://${azurerm_container_app.frontend.ingress[0].fqdn}"
}

output "acr_login_server" {
  description = "Container Registry login server (for docker push)"
  value       = azurerm_container_registry.acr.login_server
}

output "acr_admin_username" {
  description = "Container Registry admin username"
  value       = azurerm_container_registry.acr.admin_username
  sensitive   = true
}

output "log_analytics_workspace_id" {
  description = "Log Analytics Workspace ID (for monitoring)"
  value       = azurerm_log_analytics_workspace.main.id
}

output "app_insights_connection_string" {
  description = "Application Insights connection string"
  value       = azurerm_application_insights.main.connection_string
  sensitive   = true
}

output "key_vault_uri" {
  description = "Key Vault URI for secrets access"
  value       = azurerm_key_vault.main.vault_uri
}

output "ai_search_endpoint" {
  description = "Azure AI Search service endpoint"
  value       = "https://${azurerm_search_service.main.name}.search.windows.net"
}

output "next_steps" {
  description = "Quick-start commands after terraform apply"
  value = <<-EOT
    ── Next steps ──────────────────────────────────────────────────────────────

    1. Build & push Docker images:
       az acr login --name ${azurerm_container_registry.acr.name}
       docker build -t ${azurerm_container_registry.acr.login_server}/finopsai-backend:latest ./backend
       docker push ${azurerm_container_registry.acr.login_server}/finopsai-backend:latest
       docker build -t ${azurerm_container_registry.acr.login_server}/finopsai-frontend:latest ./frontend
       docker push ${azurerm_container_registry.acr.login_server}/finopsai-frontend:latest

    2. If this was a first deployment, re-run Terraform after both images exist:
       terraform apply

    3. Open the frontend:
       https://${azurerm_container_app.frontend.ingress[0].fqdn}

    4. Open the API docs:
       https://${azurerm_container_app.backend.ingress[0].fqdn}/docs

    ────────────────────────────────────────────────────────────────────────────
  EOT
}
