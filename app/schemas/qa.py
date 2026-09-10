from pydantic import BaseModel, Field, field_validator


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    equipment_id: str | None = Field(default=None, max_length=64)
    top_k: int = Field(default=3, ge=1, le=10)

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value.strip()


class Citation(BaseModel):
    source_file: str
    page: int | None = None
    source_url: str | None = None
    chunk_id: str
    excerpt: str
    distance: float | None = None


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    grounded: bool
    request_id: str
