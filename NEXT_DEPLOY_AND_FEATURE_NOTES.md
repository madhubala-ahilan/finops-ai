# Next Deploy And Feature Notes

## Current Live Status

The Azure web deployment is healthy on the last known-good image:

- Backend: `v20260602211517`
- Frontend: `v20260602211517`
- Backend health endpoint reports Azure OpenAI `gpt-4o` configured and healthy.

The newest code changes are implemented locally and verified with:

- Python compile check for changed backend files
- `npm run build` for the frontend

They are not live yet because Docker Desktop is not available on this machine and Azure Container Registry cloud builds are blocked by the subscription error:

```text
TasksOperationsNotAllowed
```

The deploy script now stops before Terraform apply if ACR cloud build fails, so this cannot silently point Container Apps at missing image tags again.

## What Was Added Locally

### 1. Multi-Agent Chat Routing

File:

- `backend/agents/langgraph_orchestrator.py`

What changed:

- Supervisor can return multiple routes, not just one agent.
- Combined user questions can run several specialists, such as FinOps + CloudOps + Forecast.
- Keyword fallback can also choose multiple agents when Azure OpenAI routing fails.
- Single-agent requests skip an extra graph supervisor call to keep ChatOps faster.

### 2. Resource-Level Cost Explorer

Files:

- `backend/services/azure_cost_service.py`
- `backend/routers/cost.py`
- `frontend/src/App.jsx`
- `frontend/src/App.css`

What changed:

- New API route: `/api/v1/cost/analysis`
- Uses Azure Consumption `usageDetails` for resource-level cost rows.
- New frontend page: `Cost Explorer`
- Filters:
  - days
  - service
  - resource group
  - region
  - resource type
  - selected resource IDs for comparison
- Charts:
  - cost by resource
  - cost by component/meter/product

### 3. Dynamic ChatOps Actions

Files:

- `frontend/src/App.jsx`
- `backend/routers/chat.py`
- `backend/agents/remediation_agent.py`
- `backend/mcp_layer/execution_server/tools.py`

What changed:

- Composer resource dropdowns use live Azure resources.
- VM actions show VMs.
- App Service actions show App Services.
- Container App actions show Container Apps.
- Storage/blob actions show Storage accounts.
- Added approval-gated delete by ARM resource ID.
- Added approval-gated create resource group.
- Added approval-gated create StorageV2 account.

## How To Deploy These Changes

Start Docker Desktop first. Then run:

```powershell
cd D:\finops-ai
.\scripts\deploy-images.ps1 -ApplyAfterPush
```

If you want to use an explicit version tag:

```powershell
cd D:\finops-ai
$TAG = "v" + (Get-Date -Format "yyyyMMddHHmmss")
.\scripts\deploy-images.ps1 -BackendTag $TAG -FrontendTag $TAG -ApplyAfterPush
```

After deploy, verify:

```powershell
curl.exe -sS https://ca-backend-finopsai-dev.graysea-1ba9897b.eastus.azurecontainerapps.io/health
curl.exe -sS https://ca-frontend-finopsai-dev.graysea-1ba9897b.eastus.azurecontainerapps.io/config.js
```

Expected:

- `build_version` should show the new tag.
- `config.js` should show the new frontend build version.

## Azure Roles Needed For Operations

Read-only pages:

- Reader
- Cost Management Reader

VM operations:

- Virtual Machine Contributor on the target scope

App Service operations:

- Website Contributor on the target scope

Container App scaling:

- Contributor or Container Apps Contributor on the target scope

Storage create/delete/blob restore:

- Storage Account Contributor
- Storage Blob Data Contributor for blob-level listing/copy

Generic delete by resource ID:

- Contributor or the matching service-specific delete permission on the target resource or resource group

## Important Safety Note

The app can now propose create/delete operations, but every mutating operation still goes into the approval queue first. Nothing destructive should execute directly from a chat message without approving the generated approval item.
