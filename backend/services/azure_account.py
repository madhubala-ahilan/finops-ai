from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from azure.identity import ClientSecretCredential
from fastapi import Header, HTTPException, Request

from config import settings


@dataclass(frozen=True)
class AzureAccount:
    tenant_id: str
    client_id: str
    client_secret: str
    subscription_id: str

    @property
    def configured(self) -> bool:
        return all([self.tenant_id, self.client_id, self.client_secret, self.subscription_id])

    def credential(self) -> ClientSecretCredential:
        return ClientSecretCredential(
            tenant_id=self.tenant_id,
            client_id=self.client_id,
            client_secret=self.client_secret,
        )


_request_account: ContextVar[AzureAccount | None] = ContextVar("azure_account", default=None)


def configured_account() -> AzureAccount:
    return AzureAccount(
        tenant_id=settings.AZURE_TENANT_ID,
        client_id=settings.AZURE_CLIENT_ID,
        client_secret=settings.AZURE_CLIENT_SECRET,
        subscription_id=settings.AZURE_SUBSCRIPTION_ID,
    )


def current_account() -> AzureAccount:
    return _request_account.get() or configured_account()


def set_current_account(account: AzureAccount | None):
    return _request_account.set(account)


def reset_current_account(token) -> None:
    _request_account.reset(token)


def account_from_headers(
    x_azure_tenant_id: str | None = Header(default=None),
    x_azure_client_id: str | None = Header(default=None),
    x_azure_client_secret: str | None = Header(default=None),
    x_azure_subscription_id: str | None = Header(default=None),
) -> AzureAccount:
    account = AzureAccount(
        tenant_id=x_azure_tenant_id or settings.AZURE_TENANT_ID,
        client_id=x_azure_client_id or settings.AZURE_CLIENT_ID,
        client_secret=x_azure_client_secret or settings.AZURE_CLIENT_SECRET,
        subscription_id=x_azure_subscription_id or settings.AZURE_SUBSCRIPTION_ID,
    )
    if not account.configured:
        raise HTTPException(
            status_code=400,
            detail=(
                "Azure account is not connected. Provide tenant ID, client ID, "
                "client secret, and subscription ID."
            ),
        )
    return account


async def bind_azure_account(request: Request) -> None:
    account = AzureAccount(
        tenant_id=request.headers.get("x-azure-tenant-id") or settings.AZURE_TENANT_ID,
        client_id=request.headers.get("x-azure-client-id") or settings.AZURE_CLIENT_ID,
        client_secret=request.headers.get("x-azure-client-secret") or settings.AZURE_CLIENT_SECRET,
        subscription_id=request.headers.get("x-azure-subscription-id") or settings.AZURE_SUBSCRIPTION_ID,
    )
    if account.configured:
        set_current_account(account)
