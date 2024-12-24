import os
from typing import Mapping

import cleo.events.console_command_event
import cleo.events.console_events
import cleo.events.event_dispatcher
import poetry.console.application
import poetry.plugins.application_plugin
from poetry.console.commands.installer_command import InstallerCommand
from poetry.console.commands.add import AddCommand
from poetry.installation.installer import Installer
from poetry.core.packages.dependency_group import MAIN_GROUP
from poetry.utils.env import EnvManager
from cleo.io.outputs.output import Verbosity


class EnvDependencyManager:
    """Manages environment-specific dependencies in Poetry projects."""

    def __init__(self, config: Mapping):
        self.env_variable = config.get("env-variable", "POETRY_ENVIRONMENT")
        self.groups = config.get("groups", [])
        self.current_env = os.environ.get(self.env_variable)

    def get_active_groups(self):
        """Get list of active dependency groups."""
        active_groups = [MAIN_GROUP]
        if self.current_env and self.current_env in self.groups:
            active_groups.append(self.current_env)
        return active_groups

    def update_package_groups(self, package) -> None:
        """Updates package to only use current environment dependencies."""
        if not self.current_env or self.current_env not in self.groups:
            return package

        return package.with_dependency_groups(
            self.get_active_groups(),
            only=True
        )

    def setup_command(self, command, poetry) -> None:
        """Initialize command with required resources."""
        # Initialize environment if needed
        if not hasattr(command, '_env') or command._env is None:
            env_manager = EnvManager(poetry)
            venv = env_manager.create_venv()
            if venv:
                command.set_env(venv)

        # Update the poetry package
        updated_package = self.update_package_groups(poetry._package)
        if updated_package:
            poetry._package = updated_package
            if hasattr(command, 'poetry'):
                command.poetry._package = updated_package

        # Initialize installer if needed
        if isinstance(command, InstallerCommand):
            if not hasattr(command, '_installer') or command._installer is None:
                installer = Installer(
                    io=command.io,
                    env=command.env,
                    package=poetry.package,
                    locker=poetry.locker,
                    pool=poetry.pool,
                    config=poetry.config,
                )
                command.set_installer(installer)

            # Update installer package
            installer_package = self.update_package_groups(command.installer._package)
            if installer_package:
                command.installer._package = installer_package

    def should_process_command(self, command) -> bool:
        """Determines if the command should be processed by the plugin."""
        return isinstance(command, (InstallerCommand, AddCommand))


class EnvironmentDependencyPlugin(poetry.plugins.application_plugin.ApplicationPlugin):
    def __init__(self):
        self.plugin_config = None
        self.poetry = None
        self.env_manager = None

    def activate(self, application: poetry.console.application.Application):
        try:
            poetry_config = application.poetry.pyproject.data
        except Exception:
            # Not in a valid Poetry project directory
            return

        plugin_config = poetry_config.get("tool", {}).get("poetry-plugin-env-deps", {})

        if not plugin_config.get("enable", False):
            return

        self.poetry = application.poetry
        self.plugin_config = plugin_config
        self.env_manager = EnvDependencyManager(plugin_config)

        application.event_dispatcher.add_listener(
            cleo.events.console_events.COMMAND,
            self.event_listener,
            priority=100  # Higher priority to run before other plugins
        )

    def event_listener(
            self,
            event: cleo.events.console_command_event.ConsoleCommandEvent,
            event_name: str,
            dispatcher: cleo.events.event_dispatcher.EventDispatcher,
    ) -> None:
        if not self.env_manager.should_process_command(event.command):
            return

        try:
            if event.io and hasattr(event.io, 'write_line'):
                event.io.write_line(
                    f"Processing dependencies for environment: {self.env_manager.current_env}",
                    verbosity=Verbosity.DEBUG,
                )
        except Exception:
            pass  # Ignore IO errors

        self.env_manager.setup_command(event.command, self.poetry)