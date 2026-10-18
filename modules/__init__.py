"""Business modules.

Dependency rule: a module may import another module's *contract* and shared
contracts, never another module's internals. `tests/test_architecture.py`
enforces this.
"""
