from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    
    model_config = {"env_file": ".env"} # Diz onde o pydantic irá procurar as váriaveis de ambiente 
    URL_JIRA: str
    JIRA_EMAIL: str
    JIRA_API_TOKEN: str
    API_KEY_CLOCKIFY: str
    WORKSPACE_ID: str
    ALERT_DAYS_LOW: int = Field(default=3, description="Dias para o alerta de prioridade baixa")
    ALERT_DAYS_HIGH: int = Field(default=5, description="Dias para o alerta de prioridade alta")
    WORKSPACE_NAME: str | None = None
    JIRA_CUSTOMFIELD_AREA: str
    WEBHOOK_TI: str
    WEBHOOK_SOP: str
    WEBHOOK_IA: str
    WEBHOOK_FRONT: str
    WEBHOOK_DESIGN: str
    WEBHOOK_DATA: str
    WEBHOOK_BACK: str
    WEBHOOK_SEM_AREA: str
    PRIORIDADES_ALTAS: list[str] = Field(default=["Highest", "High"])
    PRIORIDADES_BAIXAS: list[str] = Field(default=["Low", "Lowest"])  
    B2_ENDPOINT_URL: str
    B2_BUCKET_NAME: str
    B2_APPLICATION_KEY: str
    B2_KEY_ID: str
    TEMP_EXCEL_PATH: str = Field(default="planilha_temp.xlsx")
    JIRA_JQL: str 
    EXCEL_CLOUD_NAME: str
    SENTRY_DSN: str
    BETTERSTACK_HEARTBEAT_URL: str
    BETTERSTACK_SOURCE_TOKEN: str
    BETTERSTACK_INGESTING_HOST: str

    @property
    def teams_webhooks(self) -> dict[str, str]:
        return {
            "ti": self.WEBHOOK_TI,
            "sop": self.WEBHOOK_SOP,
            "ia": self.WEBHOOK_IA,
            "back-end": self.WEBHOOK_BACK,
            "front-end": self.WEBHOOK_FRONT,
            "design": self.WEBHOOK_DESIGN,
            "data": self.WEBHOOK_DATA,
            "sem area": self.WEBHOOK_SEM_AREA
        }


settings = Settings()