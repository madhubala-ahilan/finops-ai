# ── container_apps.tf ─────────────────────────────────────────────────────────
# Azure Container Apps Environment + backend API + frontend UI apps.

# ── Container Apps Environment ─────────────────────────────────────────────────

resource "azurerm_container_app_environment" "main" {
  name                       = "cae-${local.prefix}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  tags                       = local.tags
}

# ── Backend Container App (FastAPI) ────────────────────────────────────────────

resource "azurerm_container_app" "backend" {
  name                         = "ca-backend-${local.prefix}"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"
  tags                         = local.tags

  registry {
    server               = azurerm_container_registry.acr.login_server
    username             = azurerm_container_registry.acr.admin_username
    password_secret_name = "acr-password"
  }

  secret {
    name  = "acr-password"
    value = azurerm_container_registry.acr.admin_password
  }

  secret {
    name  = "azure-openai-api-key"
    value = var.azure_openai_api_key
  }

  secret {
    name  = "azure-subscription-id"
    value = var.subscription_id
  }

  dynamic "secret" {
    for_each = var.bot_app_secret != "" ? [1] : []
    content {
      name  = "bot-app-secret"
      value = var.bot_app_secret
    }
  }

  template {
    min_replicas = var.backend_min_replicas
    max_replicas = var.backend_max_replicas

    # HTTP traffic-based autoscaling
    custom_scale_rule {
      name             = "http-scale"
      custom_rule_type = "http"
      metadata = {
        concurrentRequests = "50"
      }
    }

    container {
      name   = "finopsai-backend"
      image  = "${azurerm_container_registry.acr.login_server}/finopsai-backend:${var.backend_image_tag}"
      cpu    = 1.0
      memory = "2Gi"

      # ── Environment variables ────────────────────────────────────────────────
      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = var.azure_openai_endpoint
      }
      env {
        name  = "AZURE_OPENAI_DEPLOYMENT"
        value = var.azure_openai_deployment
      }
      env {
        name  = "AZURE_OPENAI_API_VERSION"
        value = var.azure_openai_api_version
      }
      env {
        name        = "AZURE_OPENAI_KEY"
        secret_name = "azure-openai-api-key"
      }
      env {
        name        = "AZURE_SUBSCRIPTION_ID"
        secret_name = "azure-subscription-id"
      }
      env {
        name  = "AZURE_APPINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.main.connection_string
      }
      env {
        name  = "COST_BUDGET_MONTHLY_USD"
        value = tostring(var.monthly_budget_usd)
      }
      env {
        name  = "CORS_ORIGINS"
        value = "*"
      }
      env {
        name  = "BOT_APP_ID"
        value = var.bot_app_id
      }
      env {
        name  = "BOT_TENANT_ID"
        value = var.bot_tenant_id
      }
      env {
        name  = "BOT_VALIDATE_AUTH"
        value = tostring(var.bot_validate_auth)
      }
      env {
        name  = "BOT_ALLOW_INSECURE_LOCAL"
        value = "false"
      }
      dynamic "env" {
        for_each = var.bot_app_secret != "" ? [1] : []
        content {
          name        = "BOT_APP_SECRET"
          secret_name = "bot-app-secret"
        }
      }

      # ── Liveness probe ───────────────────────────────────────────────────────
      liveness_probe {
        transport               = "HTTP"
        path                    = "/health"
        port                    = 8080
        interval_seconds        = 30
        failure_count_threshold = 3
      }

      # ── Readiness probe ──────────────────────────────────────────────────────
      readiness_probe {
        transport        = "HTTP"
        path             = "/health"
        port             = 8080
        interval_seconds = 10
      }
    }
  }

  ingress {
    external_enabled           = true
    target_port                = 8080
    transport                  = "http"
    allow_insecure_connections = false

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}

# ── Frontend Container App (React/Vite served via nginx) ──────────────────────

resource "azurerm_container_app" "frontend" {
  name                         = "ca-frontend-${local.prefix}"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"
  tags                         = local.tags

  registry {
    server               = azurerm_container_registry.acr.login_server
    username             = azurerm_container_registry.acr.admin_username
    password_secret_name = "acr-password"
  }

  secret {
    name  = "acr-password"
    value = azurerm_container_registry.acr.admin_password
  }

  template {
    min_replicas = var.frontend_min_replicas
    max_replicas = var.frontend_max_replicas

    container {
      name   = "finopsai-frontend"
      image  = "${azurerm_container_registry.acr.login_server}/finopsai-frontend:${var.frontend_image_tag}"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "VITE_API_BASE_URL"
        value = "https://${azurerm_container_app.backend.ingress[0].fqdn}"
      }
      env {
        name  = "FINOPS_FRONTEND_VERSION"
        value = var.frontend_image_tag
      }

      liveness_probe {
        transport        = "HTTP"
        path             = "/health"
        port             = 80
        interval_seconds = 30
      }
    }
  }

  ingress {
    external_enabled           = true
    target_port                = 80
    transport                  = "http"
    allow_insecure_connections = false

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}

# ── Azure AI Search (RAG knowledge base) ───────────────────────────────────────

resource "azurerm_search_service" "main" {
  name                = "srch-${replace(local.prefix, "-", "")}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "basic"   # Use "standard" for production workloads
  replica_count       = 1
  partition_count     = 1
  tags                = local.tags
}
