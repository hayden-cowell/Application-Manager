from __future__ import annotations
from typing import Any
from pydantic import BaseModel


class ParseRequest(BaseModel):
    input_type: str   # 'text' | 'pdf'
    content: str      # raw text or base64-encoded PDF


class ParseResponse(BaseModel):
    profile: Any      # UserProfile
    resume: Any       # ResumeBaseline
    parse_quality: str
    parse_warnings: list[str]
    fields_requiring_followup: list[str]


class FollowupRequest(BaseModel):
    profile_id: str
    answers: dict[str, Any]


class FollowupResponse(BaseModel):
    profile: Any      # UserProfile
