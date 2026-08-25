"""Tests for PostgresClient upsert methods (scenarios #6 and #7).

Every method is exercised against a mocked SQLAlchemy Session (no real database):
the insert branch when ``scalars(...).first()`` returns ``None`` and the update
branch when it returns an existing row. The update-branch tests are also the
scenario #7 regression guard: they fail if a method ever drops ``.first()``, since
a bare ScalarResult is truthy and would send an existing-row case down the insert
path, duplicating instead of updating.
"""

from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sop_pipeline.clients.postgres_client import (
    DetalhesTarefa,
    Etiquetas,
    Funcionarios,
    Horas,
    TarefaEtiqueta,
    Tarefas,
    PostgresClient,
)
from sop_pipeline.models.schemas import Priority, Task, TaskType


def _scalar_result(first_value):
    """A stand-in for ``session.scalars(...)`` whose ``.first()`` is preset."""
    result = MagicMock()
    result.first.return_value = first_value
    return result


@contextmanager
def patched_session():
    """Patch ``Session`` in the client module and yield the session mock.

    ``Session(self.engine)`` is used as a context manager, so the returned mock's
    ``__enter__`` yields the session the upsert methods actually talk to.
    """
    session = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = session
    context.__exit__.return_value = False
    with patch("sop_pipeline.clients.postgres_client.Session", return_value=context):
        yield session


def _client() -> PostgresClient:
    """A client with a throwaway engine (never touched — Session is mocked)."""
    return PostgresClient(MagicMock())


# --- upsert_employee -------------------------------------------------------------


def test_upsert_employee_inserts_when_absent() -> None:
    """No matching row -> a new Funcionarios is added and committed."""
    with patched_session() as session:
        session.scalars.return_value = _scalar_result(None)
        _client().upsert_employee(
            "Alice Silva",
            "alice.jira@example.com",
            "alice.ck@example.com",
            "https://storage.example.com/alice.jpg",
        )

    added = session.add.call_args.args[0]
    assert isinstance(added, Funcionarios)
    assert added.canonical_name == "Alice Silva"
    assert added.clickup_email == "alice.jira@example.com"
    assert added.photo_url == "https://storage.example.com/alice.jpg"
    session.commit.assert_called_once()


def test_upsert_employee_updates_existing_without_inserting() -> None:
    """A matching row is updated in place; nothing new is added (scenario #7)."""
    existing = SimpleNamespace(
        canonical_name="Old Name",
        clickup_email="old.jira@example.com",
        clockify_email="old.ck@example.com",
        photo_url="https://storage.example.com/old.jpg",
    )
    with patched_session() as session:
        session.scalars.return_value = _scalar_result(existing)
        _client().upsert_employee(
            "New Name",
            "new.jira@example.com",
            "new.ck@example.com",
            "https://storage.example.com/new.jpg",
        )

    assert existing.canonical_name == "New Name"
    assert existing.clickup_email == "new.jira@example.com"
    assert existing.photo_url == "https://storage.example.com/new.jpg"
    session.add.assert_not_called()
    session.commit.assert_called_once()


# --- upsert_task -----------------------------------------------------------------


def _task(task_id: str = "ABC-1", title: str = "Title") -> Task:
    """A fully populated Task for upsert_task tests."""
    return Task(
        task_id=task_id,
        title=title,
        assignee="Carol Lima",
        priority=Priority.HIGH,
        status="In Progress",
        area="TI",
        creation_date=date(2026, 1, 1),
        due_date=date(2026, 2, 1),
        completion_date=None,
        task_type=TaskType.TASK,
        creator="Carol Lima",
        update_date=date(2026, 1, 5),
        turma="Primeiro Ano",
    )


def test_upsert_task_inserts_when_absent() -> None:
    """No matching task -> a new Tarefas row is added."""
    with patched_session() as session:
        session.scalars.return_value = _scalar_result(None)
        _client().upsert_task(task=_task(), responsavel_id=7)

    added = session.add.call_args.args[0]
    assert isinstance(added, Tarefas)
    assert added.task_id == "ABC-1"
    assert added.titulo == "Title"
    assert added.responsavel_id == 7
    assert added.prioridade == Priority.HIGH
    assert added.turma == "Primeiro Ano"
    session.commit.assert_called_once()


def test_upsert_task_updates_existing_without_inserting() -> None:
    """A matching task is updated in place; nothing new is added (scenario #7)."""
    existing = SimpleNamespace(
        task_id="ABC-1",
        titulo="Old Title",
        responsavel_id=1,
        area="TI",
        prioridade=Priority.LOW,
        status="Old Status",
        data_criacao=date(2026, 1, 1),
        prazo=date(2026, 2, 1),
        data_conclusao=None,
        tipo="Task",
        criador="Carol Lima",
        data_atualizacao=date(2026, 1, 5),
        turma="Old Turma",
    )
    with patched_session() as session:
        session.scalars.return_value = _scalar_result(existing)
        _client().upsert_task(task=_task(task_id="ABC-1", title="New Title"), responsavel_id=7)

    assert existing.titulo == "New Title"
    assert existing.responsavel_id == 7
    assert existing.prioridade == Priority.HIGH
    assert existing.turma == "Primeiro Ano"
    session.add.assert_not_called()
    session.commit.assert_called_once()


# --- upsert_task_detail ----------------------------------------------------------


def test_upsert_task_detail_inserts_when_absent() -> None:
    """No matching detail -> a new DetalhesTarefa row is added."""
    with patched_session() as session:
        session.scalars.return_value = _scalar_result(None)
        _client().upsert_task_detail("ABC-1", "A description")

    added = session.add.call_args.args[0]
    assert isinstance(added, DetalhesTarefa)
    assert added.task_id == "ABC-1"
    assert added.descricao == "A description"
    session.commit.assert_called_once()


def test_upsert_task_detail_updates_existing_without_inserting() -> None:
    """A matching detail is updated in place; nothing new is added (scenario #7)."""
    existing = SimpleNamespace(task_id="ABC-1", descricao="Old")
    with patched_session() as session:
        session.scalars.return_value = _scalar_result(existing)
        _client().upsert_task_detail("ABC-1", "New")

    assert existing.descricao == "New"
    session.add.assert_not_called()
    session.commit.assert_called_once()


# --- upsert_time_entry -----------------------------------------------------------


def test_upsert_time_entry_inserts_when_absent() -> None:
    """No matching entry -> a new Horas row is added."""
    with patched_session() as session:
        session.scalars.return_value = _scalar_result(None)
        _client().upsert_time_entry("entry-1", 7, date(2026, 1, 1), 1.5)

    added = session.add.call_args.args[0]
    assert isinstance(added, Horas)
    assert added.entry_id == "entry-1"
    assert added.horas == 1.5
    session.commit.assert_called_once()


def test_upsert_time_entry_updates_existing_without_inserting() -> None:
    """A matching entry is updated in place; nothing new is added (scenario #7)."""
    existing = SimpleNamespace(
        entry_id="entry-1", funcionario_id=1, data=date(2026, 1, 1), horas=1.0
    )
    with patched_session() as session:
        session.scalars.return_value = _scalar_result(existing)
        _client().upsert_time_entry("entry-1", 7, date(2026, 1, 2), 3.0)

    assert existing.horas == 3.0
    assert existing.funcionario_id == 7
    session.add.assert_not_called()
    session.commit.assert_called_once()


# --- upsert_tag_and_link ---------------------------------------------------------


def test_upsert_tag_and_link_creates_tag_and_link_when_absent() -> None:
    """A brand-new tag is created and flushed, then linked to the task."""
    with patched_session() as session:
        # First scalars() -> tag lookup (None), second -> link lookup (None).
        session.scalars.side_effect = [_scalar_result(None), _scalar_result(None)]
        _client().upsert_tag_and_link("ABC-1", "backend")

    added_types = [call.args[0] for call in session.add.call_args_list]
    assert any(isinstance(obj, Etiquetas) and obj.nome == "backend" for obj in added_types)
    assert any(isinstance(obj, TarefaEtiqueta) and obj.task_id == "ABC-1" for obj in added_types)
    session.flush.assert_called_once()
    session.commit.assert_called_once()


def test_upsert_tag_and_link_is_idempotent_when_link_exists() -> None:
    """Re-syncing an already-linked tag adds no duplicate tag or link row.

    This is the second-run case of "calling it twice with the same
    task_id/tag_name": the tag lookup and the link lookup both already return a
    row, so nothing is added.
    """
    existing_tag = SimpleNamespace(id=42, nome="backend")
    existing_link = SimpleNamespace(task_id="ABC-1", etiqueta_id=42)
    with patched_session() as session:
        session.scalars.side_effect = [
            _scalar_result(existing_tag),
            _scalar_result(existing_link),
        ]
        _client().upsert_tag_and_link("ABC-1", "backend")

    session.add.assert_not_called()
    session.flush.assert_not_called()
    session.commit.assert_called_once()
