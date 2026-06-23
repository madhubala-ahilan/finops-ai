"""
config.py — All environment variables with defaults and validation.
Uses pydantic-settings so .env is auto-loaded.
"""

from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    # Azure Service Principal
    AZURE_TENANT_ID: str = ""
    AZURE_CLIENT_ID: str = ""
    AZURE_CLIENT_SECRET: str = ""
    AZURE_SUBSCRIPTION_ID: str = ""

    # Azure OpenAI — GPT-4o
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_KEY: str = ""
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_DEPLOYMENT: str = "gpt-4o"
    AZURE_OPENAI_DEPLOYMENT_GPT4: str = ""
    AZURE_OPENAI_DEPLOYMENT_GPT35: str = ""
    AZURE_OPENAI_API_VERSION: str = "2024-02-15-preview"

    # Budget
    COST_BUDGET_MONTHLY_USD: float = 500.0

    # App
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000"

    # Optional
    TEAMS_WEBHOOK_URL: str = ""
    BOT_APP_ID: str = ""
    BOT_APP_SECRET: str = ""
    BOT_TENANT_ID: str = ""
    BOT_AUTH_TENANT: str = "botframework.com"
    BOT_VALIDATE_AUTH: bool = True
    BOT_ALLOW_INSECURE_LOCAL: bool = True
    TEAMS_DEFAULT_SERVICE_URL: str = ""
    TEAMS_DEFAULT_CONVERSATION_ID: str = ""
    LOG_ANALYTICS_WORKSPACE_ID: str = ""
    APP_INSIGHTS_APP_ID: str = ""
    APP_INSIGHTS_API_KEY: str = ""
    AZURE_SEARCH_ENDPOINT: str = ""
    AZURE_SEARCH_INDEX: str = ""
    AZURE_SEARCH_KEY: str = ""
    FINOPS_STATE_FILE: str = "finops_state.json"
    COST_CACHE_TTL_SECONDS: int = 900

    class Config:
        env_file = (".env", "backend/.env")
        env_file_encoding = "utf-8"
        extra = "ignore"

    @field_validator(
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_KEY",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_DEPLOYMENT",
        "AZURE_OPENAI_DEPLOYMENT_GPT4",
        "AZURE_OPENAI_DEPLOYMENT_GPT35",
        "AZURE_OPENAI_API_VERSION",
        mode="before",
    )
    @classmethod
    def clean_string_env(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip().strip('"').strip("'").rstrip("/")
        return v

    def model_post_init(self, __context) -> None:
        if not self.AZURE_OPENAI_KEY and self.AZURE_OPENAI_API_KEY:
            self.AZURE_OPENAI_KEY = self.AZURE_OPENAI_API_KEY
        if self.AZURE_OPENAI_DEPLOYMENT == "gpt-4o" and self.AZURE_OPENAI_DEPLOYMENT_GPT4:
            self.AZURE_OPENAI_DEPLOYMENT = self.AZURE_OPENAI_DEPLOYMENT_GPT4

    def azure_openai_configuration_issue(self) -> str | None:
        endpoint = (self.AZURE_OPENAI_ENDPOINT or "").lower()
        if not (self.AZURE_OPENAI_ENDPOINT and self.AZURE_OPENAI_KEY):
            return "Azure OpenAI is not configured."
        if self.openai_endpoint_family() == "unknown":
            return (
                "AZURE_OPENAI_ENDPOINT is not a recognized Azure OpenAI or "
                "Azure AI Foundry endpoint."
            )
        return None

    def openai_endpoint_family(self) -> str:
        endpoint = (self.AZURE_OPENAI_ENDPOINT or "").lower()
        if "services.ai.azure.com" in endpoint:
            return "azure_foundry"
        if ".openai.azure.com" in endpoint:
            return "azure_openai"
        return "unknown"

    def openai_v1_base_url(self) -> str:
        endpoint = (self.AZURE_OPENAI_ENDPOINT or "").rstrip("/")
        lower_endpoint = endpoint.lower()
        if "services.ai.azure.com" in lower_endpoint:
            resource_endpoint = endpoint.split("/models")[0].split("/openai")[0].rstrip("/")
            return f"{resource_endpoint}/openai/v1/"
        if ".openai.azure.com" in lower_endpoint:
            resource_endpoint = endpoint.split("/openai")[0].rstrip("/")
            return f"{resource_endpoint}/openai/v1/"
        return endpoint


settings = Settings()
