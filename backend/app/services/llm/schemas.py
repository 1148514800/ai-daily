from pydantic import BaseModel, Field, field_validator


class ArticleEnrichment(BaseModel):
    title_cn: str = Field(min_length=1)
    summary_cn: str
    # 3-5 short Chinese bullet points. Defaults to an empty list so a response
    # written by the older prompt (v2, no key points) still validates instead of
    # being rejected as malformed.
    key_points: list[str] = Field(default_factory=list)
    why_it_matters: str = ""
    importance_score: int = Field(ge=0, le=100)

    @field_validator("key_points", mode="before")
    @classmethod
    def _allow_an_explicit_null(cls, value: object) -> object:
        """Read a literal ``null`` as "no bullets" rather than a malformed article.

        The prompt asks for 3-5 points, but a model that has read a thin article
        may answer with ``"key_points": null`` instead of ``[]``. That is not a
        reason to discard an otherwise good Chinese summary and fall back to the
        untranslated title, so the null is normalised here.
        """
        return [] if value is None else value


class GitHubEnrichment(BaseModel):
    summary_cn: str = Field(min_length=1)
    why_it_matters: str = ""
