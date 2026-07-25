"""SQLAlchemy models and upsert operations for the Postgres/Supabase schema.

Table and column names mirror the Portuguese schema already deployed in
Supabase (funcionarios, tarefas, etiquetas, ...); renaming them on the Python
side would break every query against the real tables. Method names and local
variables have no such tie and are kept in English.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    Sequence,
    String,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Session
from sop_pipeline.models.schemas import Task


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model in this module."""


class Funcionarios(Base):
    """Employee identity, mirrors the ``funcionarios`` table."""

    __tablename__ = "funcionarios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_name = Column(String(100), nullable=False)
    jira_email = Column(
        String(150),
        CheckConstraint(
            r"jira_email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'",
            name="check_email_jira",
        ),
        nullable=False,
    )
    clockify_email = Column(
        String(150),
        CheckConstraint(
            r"clockify_email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'",
            name="check_email_clokify",
        ),
        nullable=False,
    )
    photo_url = Column(String)


class Tarefas(Base):
    """A Jira issue, mirrors the ``tarefas`` table."""

    __tablename__ = "tarefas"

    task_id = Column(String, primary_key=True)
    titulo = Column(String, nullable=False)
    responsavel_id = Column(
        Integer,
        ForeignKey("funcionarios.id", ondelete="SET NULL", name="fk_tarefas_funcionario"),
        nullable=True,
    )
    area = Column(String, nullable=False)
    prioridade = Column(String, nullable=False)
    status = Column(String, nullable=False)
    data_criacao = Column(Date, nullable=False)
    prazo = Column(Date)
    data_conclusao = Column(Date)
    tipo = Column(String, nullable=False)
    criador = Column(String, nullable=False)
    data_atualizacao = Column(Date, nullable=False)


class DetalhesTarefa(Base):
    """A task's long-form description, mirrors the ``detalhes_tarefa`` table."""

    __tablename__ = "detalhes_tarefa"

    task_id = Column(
        String, ForeignKey("tarefas.task_id", name="fk_detalhes_tarefa"), primary_key=True
    )
    descricao = Column(String, nullable=True)


class Horas(Base):
    """A Clockify time entry, mirrors the ``horas`` table."""

    __tablename__ = "horas"

    entry_id = Column(String, primary_key=True)
    funcionario_id = Column(
        Integer,
        ForeignKey("funcionarios.id", ondelete="SET NULL", name="fk_horas_funcionario"),
        nullable=True,
    )
    data = Column(Date, nullable=False)
    horas = Column(Numeric, nullable=False)


class Etiquetas(Base):
    """A distinct tag, mirrors the ``etiquetas`` table."""

    __tablename__ = "etiquetas"

    id = Column(Integer, primary_key=True)
    nome = Column(String, nullable=False, unique=True)


class TarefaEtiqueta(Base):
    """A task-tag association, mirrors the ``tarefa_etiqueta`` table."""

    __tablename__ = "tarefa_etiqueta"

    task_id = Column(
        String, ForeignKey("tarefas.task_id", name="fk_tarefa_etiqueta_tarefa"), primary_key=True
    )
    etiqueta_id = Column(
        Integer, ForeignKey("etiquetas.id", name="fk_tarefa_etiqueta_etiqueta"), primary_key=True
    )


class PostgresClient:
    """Upserts pipeline data into the Postgres/Supabase schema."""

    def __init__(self, engine) -> None:
        """Store the SQLAlchemy engine used to open sessions.

        Args:
            engine: The SQLAlchemy engine connected to the Postgres database.
        """
        self.engine = engine

    def get_employees(self) -> Sequence[Funcionarios]:
        """Fetch every employee row.

        Returns:
            Sequence[Funcionarios]: All rows in the ``funcionarios`` table.
        """
        with Session(self.engine) as session:
            result = session.scalars(select(Funcionarios))
            return result.all()

    def upsert_employee(
        self, canonical_name: str, jira_email: str, clockify_email: str, photo_url: str | None
    ) -> None:
        """Insert or update an employee, matched by either email address.

        Args:
            canonical_name: The normalized name used as the join key.
            jira_email: The email address that appears in Jira.
            clockify_email: The email address that appears in Clockify.
            photo_url: Public Supabase Storage URL for the employee's photo,
                or ``None`` when no photo has been uploaded yet.
        """
        with Session(self.engine) as session:
            existing = session.scalars(
                select(Funcionarios).where(
                    (Funcionarios.jira_email == jira_email)
                    | (Funcionarios.clockify_email == clockify_email)
                )
            ).first()

            if existing is None:
                session.add(
                    Funcionarios(
                        canonical_name=canonical_name,
                        jira_email=jira_email,
                        clockify_email=clockify_email,
                        photo_url=photo_url,
                    )
                )
            else:
                existing.canonical_name = canonical_name
                existing.jira_email = jira_email
                existing.clockify_email = clockify_email
                existing.photo_url = photo_url

            session.commit()

    def upsert_task(self, task: Task, responsavel_id: int | None) -> None:
        """Insert or update a task, matched by its Jira issue key.

        Args:
            task: The task to persist.
            responsavel_id: FK to ``funcionarios.id``, ``None`` when the
                assignee could not be mapped to an employee.
        """
        with Session(self.engine) as session:
            result = session.scalars(select(Tarefas).where(Tarefas.task_id == task.task_id)).first()

            if result is None:
                session.add(
                    Tarefas(
                        task_id=task.task_id,
                        titulo=task.title,
                        responsavel_id=responsavel_id,
                        area=task.area,
                        prioridade=task.priority,
                        status=task.status,
                        data_criacao=task.creation_date,
                        prazo=task.due_date,
                        data_conclusao=task.completion_date,
                        tipo=task.task_type,
                        criador=task.creator,
                        data_atualizacao=task.update_date,
                    )
                )
            else:
                result.task_id = task.task_id
                result.titulo = task.title
                result.responsavel_id = responsavel_id
                result.area = task.area
                result.prioridade = task.priority
                result.status = task.status
                result.data_criacao = task.creation_date
                result.prazo = task.due_date
                result.data_conclusao = task.completion_date
                result.tipo = task.task_type
                result.criador = task.creator
                result.data_atualizacao = task.update_date

            session.commit()

    def upsert_task_detail(self, task_id: str, descricao: str | None) -> None:
        """Insert or update a task's description, matched by its Jira issue key.

        Args:
            task_id: Jira issue key; the upsert key.
            descricao: Flattened plain-text description, or ``None`` when empty.
        """
        with Session(self.engine) as session:
            result = session.scalars(
                select(DetalhesTarefa).where(DetalhesTarefa.task_id == task_id)
            ).first()

            if result is None:
                session.add(DetalhesTarefa(task_id=task_id, descricao=descricao))
            else:
                result.task_id = task_id
                result.descricao = descricao

            session.commit()

    def upsert_time_entry(self, entry_id: str, funcionario_id: int | None, data, horas) -> None:
        """Insert or update a time entry, matched by its Clockify entry ID.

        Args:
            entry_id: Clockify entry ID; the upsert key.
            funcionario_id: FK to ``funcionarios.id``, ``None`` when the
                employee could not be mapped.
            data: Local date the entry started.
            horas: Duration in hours.
        """
        with Session(self.engine) as session:
            result = session.scalars(select(Horas).where(Horas.entry_id == entry_id)).first()

            if result is None:
                session.add(
                    Horas(entry_id=entry_id, funcionario_id=funcionario_id, data=data, horas=horas)
                )
            else:
                result.entry_id = entry_id
                result.funcionario_id = funcionario_id
                result.data = data
                result.horas = horas

            session.commit()

    def upsert_tag_and_link(self, task_id: str, tag_name: str) -> None:
        """Insert or update a tag and link it to a task.

        The tag dimension row is created only when the name does not already
        exist; the association is created only when it is not already
        recorded, since a task can be synced more than once.

        Args:
            task_id: Jira issue key.
            tag_name: The tag name to resolve or create.
        """
        with Session(self.engine) as session:
            tag = session.scalars(select(Etiquetas).where(Etiquetas.nome == tag_name)).first()

            if tag is None:
                tag = Etiquetas(nome=tag_name)
                session.add(tag)
                session.flush()

            link = session.scalars(
                select(TarefaEtiqueta).where(
                    TarefaEtiqueta.task_id == task_id, TarefaEtiqueta.etiqueta_id == tag.id
                )
            ).first()

            if link is None:
                session.add(TarefaEtiqueta(task_id=task_id, etiqueta_id=tag.id))

            session.commit()
