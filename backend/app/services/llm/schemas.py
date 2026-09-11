from pydantic import BaseModel, Field


class ArticleEnrichment(BaseModel):
    title_cn: str = Field(min_length=1)
    summary_cn: str
    why_it_matters: str = ""
    importance_score: int = Field(ge=0, le=100)
