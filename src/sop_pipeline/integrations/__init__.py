"""Outbound integrations: the spreadsheet, Teams alerts and object storage.

Import the concrete modules directly (``from sop_pipeline.integrations.excel_writer
import ExcelWriter``). This package deliberately re-exports nothing, so importing
the spreadsheet writer does not drag in the settings — and therefore a fully
populated ``.env`` — through the notifier and storage client.
"""
