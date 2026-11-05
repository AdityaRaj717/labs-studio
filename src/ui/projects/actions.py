"""Project actions shared by the sidebar picker and the Projects page.

Each asks what it needs in a dialog, reports problems in a message box and
returns the affected project (or None when cancelled or refused).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QWidget

from src.i18n import tr
from src.projects import Project, ProjectBusyError, ProjectStore

log = logging.getLogger(__name__)


def _ask_name(parent: QWidget, title: str, text: str = "") -> str | None:
    name, ok = QInputDialog.getText(parent, title, tr("proj_name"), text=text)
    return name.strip() if ok and name.strip() else None


def switch(parent: QWidget, store: ProjectStore, pid: str) -> Project | None:
    try:
        return store.activate(pid)
    except ProjectBusyError:
        QMessageBox.information(parent, tr("nav_projects"), tr("proj_busy"))
        return None


def new_project(parent: QWidget, store: ProjectStore, settings_from: str | None = None) -> Project | None:
    title = tr("proj_duplicate") if settings_from else tr("proj_new")
    suggested = tr("proj_copy_of", name=store.projects[settings_from].name) if settings_from else ""
    name = _ask_name(parent, title, suggested)
    if name is None:
        return None
    try:
        project = store.create(name, settings_from=settings_from)
    except ValueError as exc:
        QMessageBox.warning(parent, title, str(exc))
        return None
    log.info("Project created: %s", project.name)
    switch(parent, store, project.id)
    return project


def rename_project(parent: QWidget, store: ProjectStore, pid: str) -> Project | None:
    name = _ask_name(parent, tr("proj_rename"), store.projects[pid].name)
    if name is None:
        return None
    try:
        return store.rename(pid, name)
    except ValueError as exc:
        QMessageBox.warning(parent, tr("proj_rename"), str(exc))
        return None


def delete_project(parent: QWidget, store: ProjectStore, pid: str) -> bool:
    project = store.projects[pid]
    if len(store.projects) <= 1:
        QMessageBox.information(parent, tr("proj_delete"), tr("proj_delete_last"))
        return False
    box = QMessageBox(QMessageBox.Icon.Question, tr("proj_delete"),
                      tr("proj_delete_confirm", name=project.name, folder=str(project.output_dir)), parent=parent)
    keep = box.addButton(tr("proj_delete_keep"), QMessageBox.ButtonRole.AcceptRole)
    wipe = box.addButton(tr("proj_delete_files"), QMessageBox.ButtonRole.DestructiveRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(keep)
    box.exec()
    clicked = box.clickedButton()
    if clicked not in (keep, wipe):
        return False
    try:
        store.delete(pid, delete_files=clicked is wipe)
    except (ValueError, ProjectBusyError) as exc:
        QMessageBox.warning(parent, tr("proj_delete"), str(exc) if isinstance(exc, ValueError) else tr("proj_busy"))
        return False
    log.info("Project deleted: %s%s", project.name, " (with its files)" if clicked is wipe else "")
    return True


def open_folder(store: ProjectStore, pid: str) -> None:
    folder = store.projects[pid].output_dir
    folder.mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def change_output_dir(parent: QWidget, store: ProjectStore, pid: str) -> None:
    folder = QFileDialog.getExistingDirectory(parent, tr("proj_output_dir"), str(store.projects[pid].output_dir))
    if folder:
        store.set_output_dir(pid, folder)


def open_in_flow(parent: QWidget, store: ProjectStore, pid: str) -> None:
    """Open (or create) the project's Flow project in the shared Chrome, in the background."""
    from src.web.flow_mcp import open_project_async

    if store.active is None or store.active.id != pid:
        if switch(parent, store, pid) is None:
            return
        if store.settings.get("web.flow_open_on_switch", True):
            return  # switching already opens it
    open_project_async(store.projects[pid])


def bind_flow(parent: QWidget, store: ProjectStore, pid: str, client=None) -> Project | None:
    """Pick one of Flow's projects (``flow_list_projects``) and store its url on this project."""
    from PySide6.QtWidgets import QApplication

    from src.web.production_actions import ActionError, ProductionActions

    if client is None:
        from src.web.flow_mcp import flow_mcp

        client = flow_mcp().client
    project = store.projects[pid]
    # shortcut: blocks the window while Flow lists (seconds); move to a thread if it gets slow.
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        found = ProductionActions(client).list_projects()
    except ActionError as exc:
        QMessageBox.warning(parent, tr("proj_bind_flow"), tr("proj_bind_failed", message=exc.message))
        return None
    finally:
        QApplication.restoreOverrideCursor()
    found = [p for p in found if p.get("url")]
    if not found:
        QMessageBox.information(parent, tr("proj_bind_flow"), tr("proj_bind_none"))
        return None
    labels = [f"{p.get('title') or '—'}  ({p['url']})" for p in found]
    current = next((i for i, p in enumerate(found) if p["url"] == project.flow_url), 0)
    choice, ok = QInputDialog.getItem(parent, tr("proj_bind_flow"), tr("proj_bind_pick", name=project.name),
                                      labels, current, False)
    if not ok:
        return None
    picked = found[labels.index(choice)]
    project.set_flow(picked["url"], str(picked.get("title") or ""))
    return project
