from enum import Enum
from pydantic import BaseModel, computed_field, Field, EmailStr
from datetime import date

class Priority(str, Enum):
    HIGHEST = "Highest"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    LOWEST = "Lowest"

class StatusTerm(Enum):
    CONCLUIDO = "Concluído"
    ATRASADO = "Atrasado"
    ATENÇÃO = "Atenção"
    NO_PRAZO = "No prazo"
    SEM_PRAZO = "Sem prazo"

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
    priority: Priority
    status: str
    area: str | None = None
    creation_date: date 
    term: date | None = None
    completion_date:  date | None = None
    type: TypeTask
    creator: str | None = None
    update_date: date | None = None
    responsible_email: EmailStr | None = None
    tags: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def days_remaining(self) -> int | None:
        if self.term is None:
            return None
        return (self.term - date.today()).days

    @computed_field
    @property
    def its_late(self) -> str | None:
        if self.term is None:
            return None
        return "SIM" if self.term < date.today() else "NÃO"


    @computed_field
    @property
    def status_term(self) -> str:
        if self.completion_date is not None:
            s = StatusTerm.CONCLUIDO
        elif self.term is not None:
            days_until_deadline = (self.term - date.today()).days
            if self.term < date.today():
                s = StatusTerm.ATRASADO
            elif 0 < days_until_deadline <= 3:
                s = StatusTerm.ATENÇÃO
            else: 
                s = StatusTerm.NO_PRAZO
        else:
            s = StatusTerm.SEM_PRAZO
        return s.value

class RegistroHoras(BaseModel):
    id: str
    funcionario: str
    data: date
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

