from pydantic import BaseModel, Field


class TenantRulePreferenceOut(BaseModel):
    rule_id: str
    suppressed: bool


class TenantRulePreferenceUpsert(BaseModel):
    rule_id: str = Field(min_length=1, max_length=32)
    suppressed: bool = True
