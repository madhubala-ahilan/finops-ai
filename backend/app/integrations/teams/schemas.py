from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChannelAccount(BaseModel):
    id: str = ""
    name: str = ""
    aad_object_id: str = Field(default="", alias="aadObjectId")

    class Config:
        populate_by_name = True
        extra = "allow"


class ConversationAccount(BaseModel):
    id: str = ""
    name: str = ""
    conversation_type: str = Field(default="", alias="conversationType")
    tenant_id: str = Field(default="", alias="tenantId")

    class Config:
        populate_by_name = True
        extra = "allow"


class TeamsChannelData(BaseModel):
    tenant: dict[str, Any] = {}
    team: dict[str, Any] = {}
    channel: dict[str, Any] = {}

    class Config:
        extra = "allow"


class TeamsActivity(BaseModel):
    type: str = ""
    id: str = ""
    timestamp: str = ""
    service_url: str = Field(default="", alias="serviceUrl")
    channel_id: str = Field(default="", alias="channelId")
    from_property: ChannelAccount = Field(default_factory=ChannelAccount, alias="from")
    recipient: ChannelAccount = Field(default_factory=ChannelAccount)
    conversation: ConversationAccount = Field(default_factory=ConversationAccount)
    text: str = ""
    text_format: str = Field(default="", alias="textFormat")
    value: dict[str, Any] | None = None
    channel_data: TeamsChannelData | dict[str, Any] = Field(default_factory=dict, alias="channelData")
    locale: str = ""
    attachments: list[dict[str, Any]] = []

    class Config:
        populate_by_name = True
        extra = "allow"


class TeamsNotificationRequest(BaseModel):
    title: str
    text: str
    severity: str = "info"
    conversation_id: str = ""
    service_url: str = ""
    card: dict[str, Any] | None = None
