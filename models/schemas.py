from enum import Enum
from pydantic import BaseModel

class Prioridade(Enum):
    HIGHEST = "Highest"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    LOWEST = "Lowest"

class StatusPrazo(Enum):
    CONCLUIDO = "Concluído"
    ATRASADO = "Atrasado"
    ATENÇÃO = "Atenção"
    NO_PRAZO = "No prazo"
    SEM_PRAZO = "Sem Prazo"

class Tarefa(BaseModel):
    id: 