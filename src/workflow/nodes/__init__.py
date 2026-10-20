"""Every module here is imported by ``registry.default_registry()``.

Add a node type by dropping a module in this folder that calls
``src.workflow.registry.register(...)`` at import time. Nothing else changes.
"""
