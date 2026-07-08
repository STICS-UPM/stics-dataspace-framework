import re

from pydantic import BaseModel, EmailStr, field_validator

CONNECTOR_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,19}$")


class RegisterRequest(BaseModel):
    email: EmailStr
    organization_name: str

    @field_validator("organization_name")
    @classmethod
    def organization_name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("organization_name must not be blank")
        return value


class RegisterResponse(BaseModel):
    client_id: int
    api_key: str
    status: str
    message: str


class ClientSummary(BaseModel):
    id: int
    email: str
    organization_name: str
    status: str
    created_at: float
    approved_at: float | None = None


class ConnectorRequest(BaseModel):
    connector_name: str
    public_hostname: str
    target_vm_ip: str
    confirm_tls_regeneration: bool = False

    @field_validator("connector_name")
    @classmethod
    def connector_name_valid(cls, value: str) -> str:
        if not CONNECTOR_NAME_PATTERN.match(value):
            raise ValueError(
                "connector_name must be 2-20 characters, lowercase letters, digits, "
                "and hyphens only, starting with a letter"
            )
        return value


class ConnectorStatus(BaseModel):
    connector_name: str
    public_hostname: str
    status: str
    detail: str = ""
