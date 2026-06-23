# Microsoft Teams Integration

This document explains how the Microsoft Teams bot channel is wired into the existing FinOps.AI platform.

## Architecture

```text
Microsoft Teams
  -> Azure Bot Service
  -> POST /api/v1/teams/messages
  -> Bot Framework auth validation
  -> Existing LangGraph run_agent()
  -> Existing specialist agents
  -> Existing MCP / Azure SDK tools
  -> Teams reply or Adaptive Approval Card
```

The Teams bot does not create a second AI pipeline. It reuses the existing LangGraph entry point and the same approval/remediation services used by the web app.

## New Backend Files

- `backend/app/integrations/teams/schemas.py`
- `backend/app/integrations/teams/auth.py`
- `backend/app/integrations/teams/adapter.py`
- `backend/app/integrations/teams/cards.py`
- `backend/app/integrations/teams/handlers.py`
- `backend/app/integrations/teams/notifications.py`
- `backend/app/integrations/teams/routes.py`

FastAPI route registration is in:

- `backend/main.py`

## Endpoints

### Activity endpoint

```text
POST /api/v1/teams/messages
```

Use this as the Azure Bot messaging endpoint:

```text
https://<backend-host>/api/v1/teams/messages
```

### Health

```text
GET /api/v1/teams/health
```

Shows whether bot auth is configured and how many Teams conversation references have been saved.

### Conversation references

```text
GET /api/v1/teams/conversations
```

Lists remembered Teams conversations. A user or channel must message the bot once before proactive notifications have a conversation reference.

### Proactive notification

```text
POST /api/v1/teams/notify
```

Example body:

```json
{
  "title": "Budget threshold exceeded",
  "text": "Current Azure spend is above the configured threshold.",
  "severity": "warning"
}
```

## Environment Variables

Required:

```env
BOT_APP_ID=
BOT_APP_SECRET=
BOT_TENANT_ID=
```

Optional:

```env
BOT_AUTH_TENANT=botframework.com
BOT_VALIDATE_AUTH=true
BOT_ALLOW_INSECURE_LOCAL=true
TEAMS_DEFAULT_SERVICE_URL=
TEAMS_DEFAULT_CONVERSATION_ID=
TEAMS_WEBHOOK_URL=
```

Notes:

- `BOT_APP_ID` is the Azure Bot / App Registration app ID.
- `BOT_APP_SECRET` is the client secret for the app registration.
- `BOT_TENANT_ID` is your Entra tenant ID.
- `BOT_VALIDATE_AUTH=true` should be used in production.
- `BOT_VALIDATE_AUTH=false` is only for local Bot Framework Emulator testing.

## Local Testing With Uvicorn

Start backend:

```powershell
cd D:\finops-ai\backend
.\.venv\Scripts\Activate.ps1
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Check:

```powershell
curl.exe http://127.0.0.1:8000/api/v1/teams/health
```

## Local Teams Testing With Ngrok

Start tunnel:

```powershell
ngrok http 8000
```

Set Azure Bot messaging endpoint to:

```text
https://<ngrok-host>/api/v1/teams/messages
```

Then install/open the Teams app and message the bot:

```text
show my azure cost
list unhealthy resources
forecast next month spend
stop vm my-vm rg my-resource-group
```

## Local Teams Testing With Dev Tunnels

Start tunnel:

```powershell
devtunnel host -p 8000 --allow-anonymous
```

Set Azure Bot messaging endpoint to:

```text
https://<devtunnel-host>/api/v1/teams/messages
```

## Bot Framework Emulator

For emulator-only testing:

```env
BOT_VALIDATE_AUTH=false
```

Then point the emulator to:

```text
http://127.0.0.1:8000/api/v1/teams/messages
```

Do not use `BOT_VALIDATE_AUTH=false` in production.

## Adaptive Approval Cards

If an agent creates approval requests, Teams returns an Adaptive Card with:

- approval ID
- action
- resource
- risk
- approve button
- reject button

Approve executes the same remediation path as the dashboard approval page.

## Proactive Notifications

The app saves a Teams conversation reference whenever the bot receives an activity. After that, agents or backend endpoints can call:

```python
from app.integrations.teams.notifications import send_notification
```

Example alert types:

- budget threshold exceeded
- unexpected spend spike
- unhealthy resource
- blob restored successfully

## Production Deployment

Set these variables in `terraform/terraform.tfvars` or your CI/CD secret store:

```hcl
bot_app_id       = "<azure-bot-app-id>"
bot_app_secret   = "<azure-bot-client-secret>"
bot_tenant_id    = "<teams-or-bot-tenant-id>"
bot_validate_auth = true
```

Terraform maps them into the backend Container App as environment variables and stores `BOT_APP_SECRET` as a Container App secret.

Set Azure Bot messaging endpoint to:

```text
https://ca-backend-finopsai-dev.graysea-1ba9897b.eastus.azurecontainerapps.io/api/v1/teams/messages
```

Redeploy backend image after code changes:

```powershell
cd D:\finops-ai
.\scripts\deploy-images.ps1 -ApplyAfterPush
```

## Troubleshooting

### 401 Missing Bot Framework Authorization header

Teams/Azure Bot did not include the bearer token, or you called the endpoint manually with auth validation enabled.

For manual local tests only, set:

```env
BOT_VALIDATE_AUTH=false
```

### 500 BOT_APP_ID and BOT_APP_SECRET must be configured

The backend cannot validate or reply to Teams without bot credentials.

### Teams message arrives but no proactive notifications work

The bot must receive at least one message first so the backend can save the conversation reference.

### Approval card succeeds but execution fails

The approval path is working, but the Azure service principal likely lacks the role needed for that action. Check the execution error in the Teams reply and the Approval audit log.

## Production Validation Checklist

1. `GET /api/v1/teams/health` returns `bot_auth_configured=true`.
2. Azure Bot messaging endpoint is `/api/v1/teams/messages`.
3. Teams bot replies to `show my azure cost`.
4. Teams bot replies to `list unhealthy resources`.
5. Teams bot creates an approval card for a mutating request.
6. Approve/reject buttons update the approval status.
7. Proactive notification test sends an Adaptive Card to Teams.
