# FinOps.AI Code Files For Line-By-Line Architecture Review

Use this file as the handoff list for ChatGPT. Upload or paste the files below and ask:

> Explain these files line by line, then explain how the full FinOps.AI architecture works end to end: frontend, FastAPI, agents, MCP tools, Azure services, approval execution, security posture, Terraform deployment, and runtime flow.

## 1. Frontend Application

- `D:\finops-ai\frontend\src\App.jsx`
  - Main React SPA.
  - Contains connection screen, Operations dashboard, Cost Explorer, CloudOps inventory, Security page, Forecast, Anomalies, Approvals, Architecture, Settings, and ChatOps composer.
  - Explains how API calls are made, Azure headers are sent, charts are rendered, approvals are decided, and resources are filtered.

- `D:\finops-ai\frontend\src\App.css`
  - Full UI styling for light/dark mode, cards, charts, resource tables, ChatOps panel, approval states, and interactive architecture workflow.

- `D:\finops-ai\frontend\Dockerfile`
  - Frontend container build.
  - Shows Vite build and nginx serving flow.

- `D:\finops-ai\frontend\nginx.conf`
  - nginx static site config for production container.

## 2. FastAPI Application Core

- `D:\finops-ai\backend\main.py`
  - FastAPI entry point.
  - Registers CORS, health/debug endpoints, and all API routers.

- `D:\finops-ai\backend\config.py`
  - Settings model.
  - Loads Azure credentials, Azure OpenAI settings, CORS, budget, Teams/Bot settings, and runtime environment.

- `D:\finops-ai\backend\models\schemas.py`
  - Pydantic request/response schemas.
  - Defines approval, cost, forecast, anomaly, cloud resource, and agent payload models.

## 3. API Routers

- `D:\finops-ai\backend\routers\azure.py`
  - Azure connection validation endpoint.

- `D:\finops-ai\backend\routers\cost.py`
  - Cost summary, cost by service, and resource-level cost analysis endpoints.

- `D:\finops-ai\backend\routers\cloudops.py`
  - Resource inventory and resource health endpoints.

- `D:\finops-ai\backend\routers\security.py`
  - Security posture endpoint.
  - Calls Defender Resource Graph and Azure Policy compliance.

- `D:\finops-ai\backend\routers\forecast.py`
  - Forecast endpoint.
  - Uses cost trend data and ML forecast logic.

- `D:\finops-ai\backend\routers\anomalies.py`
  - Cost anomaly detection and Azure Advisor recommendations endpoints.

- `D:\finops-ai\backend\routers\approvals.py`
  - Approval queue and approval decision endpoint.
  - Calls transactional execution service.

- `D:\finops-ai\backend\routers\chat.py`
  - ChatOps endpoint.
  - Runs LangGraph first, then falls back to direct live Azure tools when needed.

- `D:\finops-ai\backend\routers\mcp_router_endpoint.py`
  - Lists and executes MCP tools from the registry.

## 4. Azure Account And State Services

- `D:\finops-ai\backend\services\azure_account.py`
  - Per-request Azure credential binding using ContextVar.
  - Lets every request use the Azure account supplied by the frontend headers.

- `D:\finops-ai\backend\services\approval_service.py`
  - Approval storage, pending count, decision recording, and execution attempt persistence.

- `D:\finops-ai\backend\services\approval_execution_service.py`
  - Transactional approval execution.
  - Success marks approval approved.
  - Failure keeps approval pending and records `last_execution_result`.

- `D:\finops-ai\backend\services\audit_service.py`
  - Append-only audit record service.

## 5. Azure Data Services

- `D:\finops-ai\backend\services\azure_cost_service.py`
  - Azure Cost Management queries.
  - Handles throttling, caching, INR currency, fallback to Consumption usageDetails, and service/resource breakdowns.

- `D:\finops-ai\backend\services\azure_resource_service.py`
  - Azure Resource Graph, Resource Health, and Azure Advisor.
  - Feeds CloudOps, ChatOps, and resource dropdowns.

- `D:\finops-ai\backend\services\azure_monitor_service.py`
  - Azure Monitor metrics and alert summary.

- `D:\finops-ai\backend\services\azure_policy_service.py`
  - Azure Policy Insights compliance summary.

## 6. Agent Layer

- `D:\finops-ai\backend\agents\base_agent.py`
  - Shared agent base class and Azure OpenAI client setup.

- `D:\finops-ai\backend\agents\router.py`
  - Agent registry and keyword-based fallback router.

- `D:\finops-ai\backend\agents\langgraph_orchestrator.py`
  - LangGraph supervisor workflow.
  - Routes user messages across multiple specialists and tool calls.

- `D:\finops-ai\backend\agents\finops_agent.py`
  - Cost analysis specialist.

- `D:\finops-ai\backend\agents\cloudops_agent.py`
  - Resource inventory, health, and Advisor specialist.

- `D:\finops-ai\backend\agents\security_agent.py`
  - Defender/Policy security posture specialist.
  - Includes clearly labelled demo finding only when live Defender rows are empty.

- `D:\finops-ai\backend\agents\forecasting_agent.py`
  - Forecast narrative specialist.

- `D:\finops-ai\backend\agents\anomaly_agent.py`
  - Anomaly detection specialist.

- `D:\finops-ai\backend\agents\governance_agent.py`
  - Policy and safety decision engine.

- `D:\finops-ai\backend\agents\remediation_agent.py`
  - Approval-gated execution agent.
  - Normalizes action aliases, parses ARM IDs, resolves resource groups, and invokes MCP execution tools.

- `D:\finops-ai\backend\agents\alert_agent.py`
  - Notification dispatch agent for Teams, Twilio, and email channels.

## 7. MCP Tool Layer

- `D:\finops-ai\backend\mcp_layer\tool_registry.py`
  - In-process MCP-style tool registry, governance checks, stats, and audit.

- `D:\finops-ai\backend\mcp_layer\tools.py`
  - Decorator-based tool schema used by LangGraph.

- `D:\finops-ai\backend\mcp_layer\finops_server\tools.py`
  - Cost, budget, forecast, anomaly, and Advisor tools.

- `D:\finops-ai\backend\mcp_layer\cloudops_server\tools.py`
  - Resource inventory, health, monitor, blob, App Insights, and incident tools.

- `D:\finops-ai\backend\mcp_layer\execution_server\tools.py`
  - Real Azure execution tools.
  - Stop/start/restart/resize VM, App Service start/stop/restart, Container App scale, restore blob, delete resource, create resource group, create storage account.

- `D:\finops-ai\backend\mcp_layer\knowledge_server\tools.py`
  - Local FinOps knowledge, troubleshooting playbooks, Azure docs search stubs, and pricing info.

- `D:\finops-ai\backend\mcp_layer\notification_server\tools.py`
  - Teams, email, and voice notification tools.

## 8. ML Layer

- `D:\finops-ai\backend\ml\isolation_forest.py`
  - Isolation Forest anomaly detection from daily cost trend.

- `D:\finops-ai\backend\ml\xgboost_forecast.py`
  - XGBoost, linear, and average fallback forecast logic.

## 9. Teams Integration Files

- `D:\finops-ai\backend\app\integrations\teams\routes.py`
- `D:\finops-ai\backend\app\integrations\teams\handlers.py`
- `D:\finops-ai\backend\app\integrations\teams\adapter.py`
- `D:\finops-ai\backend\app\integrations\teams\auth.py`
- `D:\finops-ai\backend\app\integrations\teams\cards.py`
- `D:\finops-ai\backend\app\integrations\teams\notifications.py`
- `D:\finops-ai\backend\app\integrations\teams\schemas.py`

These show how Teams messages and Adaptive Card approval actions plug into the same ChatOps and approval execution pipeline.

## 10. Terraform And Deployment

- `D:\finops-ai\terraform\main.tf`
  - Resource group, ACR, Log Analytics, Application Insights, Key Vault, budget, and secrets.

- `D:\finops-ai\terraform\container_apps.tf`
  - Azure Container Apps environment, backend app, frontend app, probes, env vars, ingress, and AI Search.

- `D:\finops-ai\terraform\variables.tf`
  - Deployment variables.

- `D:\finops-ai\terraform\outputs.tf`
  - Backend/frontend URLs, ACR login server, Key Vault URI.

- `D:\finops-ai\scripts\deploy-images.ps1`
  - Docker/ACR build and Terraform apply helper.

## 11. Suggested ChatGPT Prompt

Paste this with the files:

```text
I am learning this FinOps.AI project. Explain every file line by line, then explain the full architecture end to end. Focus on:
1. How React sends Azure credentials and renders pages.
2. How FastAPI routers receive requests.
3. How AzureAccount ContextVar works.
4. How LangGraph routes to agents.
5. How MCP tools are registered and executed.
6. How approval execution is transactional.
7. How Azure SDK calls mutate resources safely.
8. How Cost Management throttling fallback works.
9. How Security posture and demo finding work.
10. How Terraform deploys the platform.
```
