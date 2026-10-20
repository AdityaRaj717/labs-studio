"""Video Editor page (Phase 8)."""


def editor_page():
    """Page factory for the router; imports the page lazily."""
    from src.ui.editor.page import VideoEditorPage

    return VideoEditorPage()
