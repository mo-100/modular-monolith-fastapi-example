"""Run Alembic for one module or all modules.

Each module has its own script directory, versions and version table
(``alembic_version_<module>`` in ``public``), so migrations remain isolated and
a module can be removed without touching another module's history.

Examples:
    python -m scripts.migrate upgrade all
    python -m scripts.migrate upgrade inventory
    python -m scripts.migrate downgrade orders base
    python -m scripts.migrate revision notifications -m "add channel"
"""

import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config

from shared.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
MODULES = ("inventory", "orders", "notifications")


def config_for(module: str, database_url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option(
        "script_location", str(ROOT / "modules" / module / "migrations")
    )
    config.set_main_option("sqlalchemy.url", database_url)
    config.set_main_option("prepend_sys_path", str(ROOT))
    return config


def upgrade_module(module: str, database_url: str, revision: str = "head") -> None:
    command.upgrade(config_for(module, database_url), revision)


def _config(module: str) -> Config:
    return config_for(module, get_settings().database_url)


def _selected(module: str) -> tuple[str, ...]:
    return MODULES if module == "all" else (module,)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)

    upgrade = subparsers.add_parser("upgrade")
    upgrade.add_argument("module", choices=(*MODULES, "all"))
    upgrade.add_argument("revision", nargs="?", default="head")

    downgrade = subparsers.add_parser("downgrade")
    downgrade.add_argument("module", choices=MODULES)
    downgrade.add_argument("revision", nargs="?", default="base")

    current = subparsers.add_parser("current")
    current.add_argument("module", choices=(*MODULES, "all"))

    revision = subparsers.add_parser("revision")
    revision.add_argument("module", choices=MODULES)
    revision.add_argument("-m", "--message", required=True)
    revision.add_argument("--autogenerate", action="store_true")

    args = parser.parse_args()

    if args.action == "upgrade":
        for module in _selected(args.module):
            command.upgrade(_config(module), args.revision)
            print(f"{module}: upgraded to {args.revision}")
    elif args.action == "downgrade":
        for module in _selected(args.module):
            command.downgrade(_config(module), args.revision)
            print(f"{module}: downgraded to {args.revision}")
    elif args.action == "current":
        for module in _selected(args.module):
            command.current(_config(module))
    else:
        command.revision(
            _config(args.module),
            message=args.message,
            autogenerate=args.autogenerate,
        )


if __name__ == "__main__":
    main()
