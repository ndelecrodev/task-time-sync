from enum import Enum
from pydantic import BaseModel, computed_field, Field, EmailStr
from datetime import datetime, date

class Prioridade(str, Enum):
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

class TypeTask(str, Enum):
    BUG = "Bug"
    TASK = "Task"
    STORY = "Story"
    EPIC = "Epic"
    SUBTASK = "Subtask"

class Tarefa(BaseModel):
    id: str
    title: str 
    responsible: str
    prioridade: Prioridade
    status: str
    area: str | None = None
    data_criacao: date 
    prazo: date | None = None
    data_conclusao:  date | None = None
    tipo: TypeTask
    criador: str | None = None
    data_atualizacao: date | None = None
    etiquetas: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def dias_restantes(self) -> int | None:
        if self.prazo is None:
            return None
        return (self.prazo - date.today()).days

    @computed_field
    @property
    def esta_atrasado(self) -> str | None:
        if self.prazo is None:
            return None
        return "SIM" if self.prazo < date.today() else "NÃO"


    @computed_field
    @property
    def status_prazo(self) -> str:
        if self.data_conclusao is not None:
            s = StatusPrazo.CONCLUIDO
        elif self.prazo is not None:
            days_until_deadline = (self.prazo - date.today()).days
            if self.prazo < date.today():
                s = StatusPrazo.ATRASADO
            elif 0 < days_until_deadline <= 3:
                s = StatusPrazo.ATENÇÃO
            else: 
                s = StatusPrazo.NO_PRAZO
        else:
            s = StatusPrazo.SEM_PRAZO
        return s.value

class RegistroHoras(BaseModel):
    funcionario: str
    data: datetime
    horas: float = Field(ge=0)

class Funcionario(BaseModel):
    id_funcionario: int
    nome: str
    email: EmailStr | None = None

class Area(BaseModel):
    id_area: int
    nome_area: str

class FuncionarioArea(BaseModel):
    id_funcionario: int 
    id_area: int

class Etiqueta(BaseModel):
    id_etiqueta: int
    nome_etiqueta: str

class TarefaEtiqueta(BaseModel):
    id_tarefa: str
    id_etiqueta: int

class DetalheTarefa(BaseModel):
    id_tarefa: str
    descricao: str | None = None