from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    model_config = {"env_file": ".env"} # Diz onde o pydantic irá procurar as váriaveis de ambiente 
    URL_JIRA: str
    JIRA_EMAIL: str
    JIRA_TOKEN: str
    API_KEY_CLOCKIFY: str
    WORKSPACE_ID: str
    EXCEL_WAY: str
    ALERT_DAYS_LOW: int = Field(default=3, description="Dias para o alerta de prioridade baixa")
    ALERT_DAYS_HIGH: int = Field(default=5, description="Dias para o alerta de prioridade alta")
    WORKSPACE_NAME: str | None = None

settings = Settings()
