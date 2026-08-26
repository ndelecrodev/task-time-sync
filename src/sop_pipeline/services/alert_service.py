"""Business rules deciding which tasks deserve a deadline alert."""

from sop_pipeline.config.settings import settings
from sop_pipeline.models.schemas import Priority, Task

# Segundo Ano tasks must never trigger a Teams alert (product decision, see
# design-decisions.md). Named here rather than inlined so a third turma is
# easy to find and add later.
EXCLUDED_TURMA = "Segundo Ano"


class AlertService:
    """Selects the tasks whose deadline is close enough to warrant a warning."""

    @staticmethod
    def tasks_to_alert(tasks: list[Task]) -> list[Task]:
        """Filter the tasks that should trigger a deadline alert.

        High-priority tasks get a wider warning window than low-priority ones, so
        the team is told about the urgent work earlier. Every priority maps to a
        window: a priority with no window would never alert at all, which is how
        ``Medium`` used to be silently skipped.

        Args:
            tasks: The tasks to evaluate.

        Returns:
            list[Task]: Tasks that are still open and inside their alert window.
        """
        results = []
        for task in tasks:
            # Segundo Ano is excluded from Teams alerts entirely; no reason to
            # evaluate its urgency if it can never alert regardless of the result.
            if task.turma == EXCLUDED_TURMA:
                continue

            # A finished task never needs a deadline warning.
            if task.completion_date is not None:
                continue

            # No due date means there is no window to compare against.
            if task.days_remaining is None:
                continue

            alert_window = AlertService._alert_window(task.priority.value)
            if alert_window is not None and task.days_remaining <= alert_window:
                results.append(task)

        return results

    @staticmethod
    def _alert_window(priority: str) -> int | None:
        """Return how many days ahead a given priority starts alerting.

        Args:
            priority: The task's priority value.

        Returns:
            int | None: The window in days, or ``None`` for a priority that is not
            configured to alert.
        """
        if priority in settings.HIGH_PRIORITIES:
            return settings.ALERT_DAYS_HIGH
        if priority in settings.LOW_PRIORITIES:
            return settings.ALERT_DAYS_LOW
        if priority == Priority.MEDIUM.value:
            return settings.ALERT_DAYS_MEDIUM
        return None
