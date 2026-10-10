"""Load and validate the category/topic configuration as one atomic document."""

from pathlib import Path
from typing import Annotated, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)
from pydantic import ValidationError as PydanticValidationError

DEFAULT_CATEGORY_CONFIG_PATH = Path("config/categories.yaml")
SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class CategoryConfigError(ValueError):
    """Raised when a category configuration file cannot be parsed or validated."""


class CategoryDefinition(BaseModel):
    """One validated category and its discovery topics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: StrictStr
    slug: Annotated[StrictStr, Field(pattern=SLUG_PATTERN)]
    active: StrictBool
    display_order: Annotated[StrictInt, Field(gt=0)]
    topics: Annotated[tuple[StrictStr, ...], Field(min_length=1)]

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("category name must not be empty")
        if value != value.strip():
            raise ValueError("category name must not have surrounding whitespace")
        if value.casefold() == "all":
            raise ValueError("All is a query filter and cannot be a category")
        return value

    @field_validator("topics")
    @classmethod
    def validate_topics(cls, topics: tuple[str, ...]) -> tuple[str, ...]:
        for topic in topics:
            if not topic or topic != topic.strip():
                raise ValueError("topics must be non-empty and have no surrounding whitespace")
            if topic.casefold() == "all":
                raise ValueError("All is a query filter and cannot be a topic")
        return topics


class CategoryConfiguration(BaseModel):
    """A fully validated category configuration document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    categories: Annotated[tuple[CategoryDefinition, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def reject_duplicates(self) -> Self:
        _reject_duplicate(self.categories, "name")
        _reject_duplicate(self.categories, "slug")
        _reject_duplicate(self.categories, "display_order")

        topics: set[str] = set()
        for category in self.categories:
            for topic in category.topics:
                if topic in topics:
                    raise ValueError(f"duplicate topic: {topic!r}")
                topics.add(topic)
        return self


def _reject_duplicate(categories: tuple[CategoryDefinition, ...], field: str) -> None:
    seen: set[str | int] = set()
    for category in categories:
        value = getattr(category, field)
        if value in seen:
            raise ValueError(f"duplicate category {field}: {value!r}")
        seen.add(value)


def load_category_config(
    path: str | Path = DEFAULT_CATEGORY_CONFIG_PATH,
) -> CategoryConfiguration:
    """Read and validate a YAML file without exposing partially valid data."""

    config_path = Path(path)
    try:
        with config_path.open(encoding="utf-8") as config_file:
            raw: object = yaml.safe_load(config_file)
    except (OSError, yaml.YAMLError) as error:
        raise CategoryConfigError(
            f"Could not read category configuration {config_path}: {error}"
        ) from error

    try:
        return CategoryConfiguration.model_validate(raw)
    except PydanticValidationError as error:
        raise CategoryConfigError(
            f"Invalid category configuration {config_path}: {error}"
        ) from error


def main() -> None:
    """Validate the configured category file for local and deployment checks."""

    configuration = load_category_config()
    topic_count = sum(len(category.topics) for category in configuration.categories)
    print(
        f"Validated {len(configuration.categories)} categories and "
        f"{topic_count} topics from {DEFAULT_CATEGORY_CONFIG_PATH}"
    )
