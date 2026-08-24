"""Application settings loaded from environment variables.

All credentials and tunables come from a local ``.env`` file (see
``.env.example``); nothing is hardcoded in the source tree. The module exposes a
single ready-to-use :data:`settings` instance.
"""

from logging import getLogger

from pydantic import Field
from pydantic_settings import BaseSettings
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from sop_pipeline.clients.postgres_client import PostgresClient
from sop_pipeline.config.employees import EmployeeMapping, EmployeeRegistry

logger = getLogger(__name__)


class Settings(BaseSettings):
    """Typed access to every environment variable used by the pipeline.

    Attributes are validated by pydantic on instantiation, so a missing or
    malformed variable fails loudly at import time instead of halfway through a
    run.
    """

    # Tells pydantic-settings where to look for the environment variables.
    model_config = {"env_file": ".env"}

    CLICKUP_API_TOKEN: str
    CLICKUP_TEAM_ID: str
    CLICKUP_LIST_ID: str
    API_KEY_CLOCKIFY: str
    WORKSPACE_ID: str
    ALERT_DAYS_LOW: int = Field(
        default=3, description="Days ahead that triggers a low-priority alert"
    )
    ALERT_DAYS_HIGH: int = Field(
        default=5, description="Days ahead that triggers a high-priority alert"
    )
    ALERT_DAYS_MEDIUM: int = Field(
        default=4, description="Days ahead that triggers a medium-priority alert"
    )
    WORKSPACE_NAME: str | None = None
    CLICKUP_AREA_FIELD_ID: str
    WEBHOOK_TI: str
    WEBHOOK_SOP: str
    WEBHOOK_IA: str
    WEBHOOK_FRONT: str
    WEBHOOK_DESIGN: str
    WEBHOOK_DATA: str
    WEBHOOK_BACK: str
    WEBHOOK_NO_AREA: str
    HIGH_PRIORITIES: list[str] = Field(default=["Highest", "High"])
    LOW_PRIORITIES: list[str] = Field(default=["Low", "Lowest"])
    B2_ENDPOINT_URL: str
    B2_BUCKET_NAME: str
    B2_APPLICATION_KEY: str
    B2_KEY_ID: str
    TEMP_EXCEL_PATH: str = Field(default="planilha_temp.xlsx")
    EXCEL_CLOUD_NAME: str
    SENTRY_DSN: str
    BETTERSTACK_HEARTBEAT_URL: str
    BETTERSTACK_SOURCE_TOKEN: str
    BETTERSTACK_INGESTING_HOST: str
    DATABASE_URL: str

    def load_employee_registry(self) -> EmployeeRegistry:
        """Load and validate the employee registry from Postgres.

        Returns:
            EmployeeRegistry: The validated employee registry.

        Raises:
            SQLAlchemyError: If the database cannot be reached.
            ValueError: If any email is mapped to multiple canonical names.
        """
        try:
            employees = PostgresClient(engine).get_employees()
        except SQLAlchemyError as error:
            logger.error("Failure to connect to the database: %s", error)
            raise

        mappings = []
        for employee in employees:
            mapping = EmployeeMapping(
                canonical_name=employee.canonical_name,
                jira_email=employee.jira_email,
                clockify_email=employee.clockify_email,
            )
            mappings.append(mapping)

        registry = EmployeeRegistry(mappings)
        logger.info("Loaded %d employee mappings:", len(mappings))
        return registry

    @property
    def teams_webhooks(self) -> dict[str, str]:
        """Map an area name to the Teams webhook that serves it.

        The keys (other than the fallback) must match, in lowercase, the values
        produced by the ClickUp "area" custom field — ``Notifier`` looks the area
        up directly in this dict. ``"no area"`` is an internal fallback key and is
        never compared against ClickUp data.

        Returns:
            dict[str, str]: Area name in lowercase mapped to its webhook URL.
        """
        return {
            "ti": self.WEBHOOK_TI,
            "sop": self.WEBHOOK_SOP,
            "ia": self.WEBHOOK_IA,
            "back-end": self.WEBHOOK_BACK,
            "front-end": self.WEBHOOK_FRONT,
            "design": self.WEBHOOK_DESIGN,
            "data": self.WEBHOOK_DATA,
            "no area": self.WEBHOOK_NO_AREA,
        }


settings = Settings()

engine = create_engine(settings.DATABASE_URL)
