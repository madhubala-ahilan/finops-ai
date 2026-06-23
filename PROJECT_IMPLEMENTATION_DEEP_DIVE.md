# FinOps AI Platform Implementation Deep Dive

This document explains what has been built, which techniques are used, how the code connects end to end, and what each major feature does.

## 1. Product Goal

FinOps AI is a live Azure operations platform. It connects to an Azure subscription through service principal credentials, reads cost/resource/security data, shows interactive dashboards, and lets users ask ChatOps to inspect Azure and create approval-gated remediation actions.

The core principle is:

- Read-only insights run immediately.
- Risky infrastructure operations are queued for approval.
- Approved operations execute through Azure SDK-backed MCP execution tools.
- The same code paths are used locally and in Azure Container Apps.

## 2. Frontend Application

Main file:

- `frontend/src/App.jsx`

Styling:

- `frontend/src/App.css`
- `frontend/src/index.css`

Build and runtime config:

- `frontend/Dockerfile`
- `frontend/public/config.js`
- `scripts/deploy-images.ps1`

### 2.1 Connection Flow

The frontend stores Azure service principal details in `sessionStorage` under `finops.azure.connection`.

Every API request includes:

- `x-azure-tenant-id`
- `x-azure-client-id`
- `x-azure-client-secret`
- `x-azure-subscription-id`

The helper `azureHeaders()` prepares these headers, and `apiFetch()` sends them to the backend.

### 2.2 Operations Dashboard

The dashboard uses live backend responses:

- `/api/v1/cost/summary`
- `/api/v1/cloudops/resources`
- `/api/v1/anomalies/`
- `/api/v1/anomalies/recommendations`
- `/api/v1/forecast/30d`
- `/api/v1/approvals/`
- `/api/v1/security/posture`

It renders:

- Month-to-date spend
- Budget usage
- Resource count
- Anomaly count
- Cost trend chart
- Spend by service chart
- ChatOps command center cards

Currency formatting is centralized through `normalizeCurrency()` and `formatMoney()`. INR is rendered with rupee formatting so production and local UI use the same display logic.

### 2.3 CloudOps Inventory

The CloudOps page now includes an AI-style fuzzy search box.

Implemented helpers:

- `normalizeSearch()`
- `editDistance()`
- `resourceSearchText()`
- `resourceSearchScore()`

The search checks:

- Resource name
- Friendly type
- Raw Azure type
- Resource group
- Region
- Health/status

It tolerates small typos using edit distance and partial term matching. This lets users search naturally, for example:

- `vm`
- `virual machne`
- `storage`
- `rg-finops`
- `east us`

### 2.4 ChatOps Composer

The ChatOps composer is powered by live Azure inventory.

Relevant functions:

- `operationActions`
- `resourceTypeBucket()`
- `ChatPanel()`

The action dropdown is dynamic. It shows operations that match resource types actually returned by Azure Resource Graph.

Supported UI operations:

- Stop VM
- Start VM
- Restart VM
- Resize VM
- Restart App Service
- Stop App Service
- Start App Service
- Scale Container App
- Restore Blob
- Check Blob

The resource dropdown only lists resources matching the selected operation type:

- VM actions show VM resources.
- App Service actions show App Service resources.
- Container App scale shows Container Apps.
- Blob actions show Storage Accounts.

The composer also has a resource search field. This helps users quickly narrow the dropdown when many Azure resources exist.

### 2.5 Production Compatibility

The deployed frontend uses runtime config from `window.__FINOPS_CONFIG__`, generated in the frontend Docker image:

- `API_BASE_URL`
- `BUILD_VERSION`

This avoids rebuilding the React source just to point the frontend at a different backend URL.

## 3. Backend Application

Main entry point:

- `backend/main.py`

Configuration:

- `backend/config.py`

Schemas:

- `backend/models/schemas.py`

The backend is FastAPI. It uses per-request Azure account binding through headers and `ContextVar` storage.

### 3.1 Azure Account Binding

File:

- `backend/services/azure_account.py`

The API reads Azure credential headers and creates an `AzureAccount`.

Important functions:

- `account_from_headers()`
- `set_current_account()`
- `reset_current_account()`
- `current_account()`

This allows services and MCP tools to use the correct subscription for each request.

### 3.2 Cost Service

File:

- `backend/services/azure_cost_service.py`

Techniques used:

- Azure Cost Management Query API
- Azure Consumption usageDetails fallback
- Async request locking
- In-memory and persisted cache
- Throttling-safe fallback behavior

Why throttling happens:

Azure Cost Management Query API has strict tenant/entity/client throttles. If the frontend refreshes several cards at once, Azure may return 429. The app now falls back to cached live data or Consumption usageDetails instead of going blank.

### 3.3 Resource Inventory

File:

- `backend/services/azure_resource_service.py`

Uses Azure Resource Graph to list live subscription resources. Resource Graph is fast and free for this use case.

Returned resource fields:

- `name`
- `type`
- `raw_type`
- `region`
- `resource_group`
- `id`
- `status`

The frontend uses both `type` and `raw_type` so dynamic operation matching works reliably.

### 3.4 Forecasting

Files:

- `backend/routers/forecast.py`
- `backend/ml/xgboost_forecast.py`

Techniques:

- XGBoost forecasting when enough history exists
- Linear fallback for limited history
- Average fallback for very small history

The forecast page now renders `forecast.series` and includes notes when Azure has limited daily data.

### 3.5 Security and Governance

Files:

- `backend/agents/security_agent.py`
- `backend/services/azure_policy_service.py`
- `backend/agents/governance_agent.py`

Security uses:

- Resource Graph `securityresources`
- Azure Policy Insights where available

Governance validates risky actions before execution. It classifies actions as:

- Blocked
- Human approval required
- Auto-approved

## 4. ChatOps and Agent Flow

Main router:

- `backend/routers/chat.py`

LangGraph orchestrator:

- `backend/agents/langgraph_orchestrator.py`

Agent base:

- `backend/agents/base_agent.py`

### 4.1 GPT/LangGraph Path

The normal flow is:

1. Frontend sends message to `POST /api/v1/chat`.
2. Backend binds the Azure account.
3. LangGraph supervisor routes the message.
4. A specialist agent runs.
5. The agent may call MCP tools.
6. The final answer returns to the UI.

### 4.2 Direct Tool Fallback

If Azure OpenAI is not configured or fails, `chat.py` uses `_chatops_without_llm()`.

Direct fallback supports:

- Cost summary
- Resource listing
- Advisor recommendations
- Security posture
- Pending approvals
- Operation approval creation
- Storage account/blob inspection

This is why the chatbot can still do useful Azure work even if GPT is unavailable.

### 4.3 Blob Commands

Direct storage commands now include:

- `check blob <container>/<blob> storage_account <account>`
- `restore blob <container>/<blob> storage_account <account>`

`check blob` is read-only. `restore blob` creates an approval.

## 5. MCP Layer

Registry:

- `backend/mcp_layer/tool_registry.py`

Tool servers:

- `backend/mcp_layer/finops_server/tools.py`
- `backend/mcp_layer/cloudops_server/tools.py`
- `backend/mcp_layer/execution_server/tools.py`
- `backend/mcp_layer/knowledge_server/tools.py`
- `backend/mcp_layer/notification_server/tools.py`

### 5.1 FinOps Tools

Examples:

- Cost summary
- Cost by service
- Budget status
- Forecast spend
- Detect anomalies

### 5.2 CloudOps Tools

Examples:

- Resource inventory
- Resource health
- Monitor metrics
- Blob asset check
- App Insights errors
- Log Analytics query
- Policy compliance

### 5.3 Execution Tools

All execution tools are approval-gated.

Implemented operations:

- `stop_vm`
- `start_vm`
- `restart_vm`
- `resize_vm`
- `restart_app_service`
- `stop_app_service`
- `start_app_service`
- `restore_blob`
- `scale_container_app`

These use Azure SDK clients such as:

- `ComputeManagementClient`
- `WebSiteManagementClient`
- `BlobServiceClient`
- `ContainerAppsAPIClient`

## 6. Approval System

Files:

- `backend/routers/approvals.py`
- `backend/services/approval_service.py`
- `backend/services/audit_service.py`
- `backend/agents/remediation_agent.py`

### 6.1 Approval Creation

ChatOps parses operation commands and creates approval records through:

- `_maybe_create_operation_approval()`
- `approval_service.create_approval_request()`

Approval records include:

- ID
- Action
- Action type
- Resource
- Risk
- Params
- Created time
- Status

### 6.2 Approval Decision

Approvals can be decided from:

- The Approvals UI page
- ChatOps command such as `approve apr-...`

When approved:

1. The backend retrieves the approval.
2. The remediation agent maps `action_type` to a handler.
3. The MCP execution tool runs.
4. Audit log records the result.

### 6.3 Latest Approval Fixes

The remediation agent now auto-resolves missing resource groups from Azure Resource Graph before execution.

This fixes approvals that only contain a resource name but not `resource_group`.

The audit route `/api/v1/approvals/audit/log` is now declared before the dynamic `/{approval_id}` route so FastAPI does not treat `audit/log` as an approval ID.

The UI now displays execution errors more clearly via the approval result message.

## 7. Deployment and Infrastructure

Terraform folder:

- `terraform/main.tf`
- `terraform/container_apps.tf`
- `terraform/variables.tf`
- `terraform/outputs.tf`

Deployment script:

- `scripts/deploy-images.ps1`

### 7.1 Terraform Creates

Terraform provisions:

- Resource Group
- Azure Container Registry
- Log Analytics Workspace
- Application Insights
- Key Vault
- Container Apps Environment
- Backend Container App
- Frontend Container App
- Azure AI Search
- Budget alerts

### 7.2 Docker Images

Backend:

- FastAPI container
- Runs Uvicorn
- Receives Azure/OpenAI/Terraform env vars

Frontend:

- Vite build
- Served by nginx
- Runtime `config.js` injects backend URL and build version

### 7.3 Deploy Flow

Use:

```powershell
cd D:\finops-ai
.\scripts\deploy-images.ps1 -ApplyAfterPush
```

This builds backend and frontend images, pushes to ACR, updates Terraform image tags, and applies the new Container App revisions.

## 8. Current Feature List

Live features:

- Azure connection validation
- Live resource inventory
- Live cost summary with throttling fallback
- INR currency display
- Cost trend chart
- Service spend chart
- Cost Explorer with resource, service, component, region, type, and resource comparison filters
- Forecast page
- Anomaly page
- Advisor recommendations
- Security posture
- Policy compliance
- Approval queue
- Approval-gated execution
- ChatOps direct tool fallback
- Multi-agent ChatOps routing for combined questions
- Dynamic ChatOps operation composer with live resource-aware actions
- Approval-gated create/delete operations for selected Azure resources
- Fuzzy CloudOps resource search
- Light/dark theme
- Architecture page
- Docker and Terraform deployment

## 9. Known Remaining Work

Recommended next improvements:

- Persist approvals/audit to Cosmos DB or Azure SQL instead of local JSON.
- Add full Teams bot conversational UI.
- Add Twilio production alerting with verified sender numbers.
- Add Azure AI Search vector RAG instead of static/local knowledge fallback.
- Add CI/CD pipeline for image build and Terraform apply.
- Add role/permission validation page that checks if the service principal has the required Azure roles for each operation.
- Add operation dry-run/preflight checks before approval creation.
- Add richer create wizards for VM, Container App, App Service, Key Vault, SQL, and AKS after final role validation.

## 10. How to Validate After Deployment

1. Open frontend Container App URL.
2. Confirm sidebar build version changed.
3. Connect Azure credentials.
4. Open CloudOps and search with typo terms like `virual`, `storag`, or resource group name.
5. Open ChatOps.
6. Select an operation. The resource dropdown should only show matching live resources.
7. Compose an action and create approval.
8. Go to Approvals and approve it.
9. Check the result message and `/api/v1/approvals/audit/log`.

Useful backend endpoints:

- `/health`
- `/debug/cors`
- `/api/v1/azure/connection`
- `/api/v1/cloudops/resources`
- `/api/v1/cost/analysis`
- `/api/v1/approvals/`
- `/api/v1/approvals/audit/log`
- `/api/v1/chat/debug/openai`

## 11. Latest Scaling Update

This update makes the product less hardcoded and more resource-aware.

### 11.1 Multi-Agent Routing

File:

- `backend/agents/langgraph_orchestrator.py`

Changes:

- Supervisor now returns `routes` instead of one fixed route.
- Combined requests can run multiple specialists, for example FinOps + CloudOps for cost and resources, or Security + Approval for governance questions.
- Keyword fallback also supports multi-agent plans when Azure OpenAI routing fails.
- Single-agent requests skip an extra graph supervisor call, which keeps ChatOps faster.

### 11.2 Resource-Level Cost Explorer

Files:

- `backend/services/azure_cost_service.py`
- `backend/routers/cost.py`
- `frontend/src/App.jsx`
- `frontend/src/App.css`

Changes:

- New backend route: `/api/v1/cost/analysis`.
- Uses Azure Consumption `usageDetails` for detailed rows because it includes resource ID, resource group, region, service, meter/component, and billing currency in one feed.
- Frontend page: `Cost Explorer`.
- Filters include days, service, resource group, region, resource type, and selected resources.
- Charts show cost by resource and cost by component so users can compare specific VMs, storage accounts, apps, or any resource type returned by Azure.

### 11.3 Dynamic ChatOps Operations

Files:

- `frontend/src/App.jsx`
- `backend/routers/chat.py`
- `backend/agents/remediation_agent.py`
- `backend/mcp_layer/execution_server/tools.py`

Changes:

- Composer actions are derived from live resource types.
- VM actions show only VMs, App Service actions show App Services, Container App actions show Container Apps, and storage/blob actions show Storage accounts.
- Added generic delete by ARM resource ID. This is intentionally approval-gated and requires selecting a real resource from the live dropdown.
- Added approval-gated create resource group.
- Added approval-gated create StorageV2 account.
- Approval execution now recognizes the new action types and forwards them to MCP execution tools.

### 11.4 Safety Model

Read-only operations still run immediately:

- cost analysis
- resource inventory
- Advisor/security queries
- blob checks

Mutating operations still require approval:

- stop/start/restart/resize VM
- stop/start/restart App Service
- scale Container App
- restore blob
- delete selected resource
- create resource group
- create storage account

The application can now create approvals for more operations, but Azure will still enforce service-principal permissions. At minimum, the service principal needs appropriate scoped roles such as Reader for inventory, Cost Management Reader for costs, Virtual Machine Contributor for VM actions, Website Contributor for App Service actions, Storage Account Contributor for storage creation/deletion, and Contributor or scoped resource-specific roles for generic create/delete.
