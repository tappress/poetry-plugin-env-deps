import os
from typing import Mapping

import cleo.events.console_command_event
import cleo.events.console_events
import cleo.events.event_dispatcher
import poetry.console.application
import poetry.plugins.application_plugin
from poetry.console.commands.installer_command import InstallerCommand
from poetry.core.packages.dependency_group import MAIN_GROUP


class EnvDependencyManager:
    """Manages environment-specific dependencies in Poetry projects."""

    def __init__(self, config: Mapping):
        self.env_variable = config.get("env-variable", "POETRY_ENVIRONMENT")
        self.groups = config.get("groups", [])
        self.current_env = os.environ.get(self.env_variable)

    def update_installer_package(self, command: InstallerCommand) -> None:
        """Updates the installer package to only use current environment dependencies."""
        if not self.current_env or self.current_env not in self.groups:
            return

        active_groups = [MAIN_GROUP]
        if self.current_env:
            active_groups.append(self.current_env)

        # Create a new package with only the active groups
        package = command.installer._package.with_dependency_groups(
            active_groups,
            only=True
        )

        # Update the installer's package
        command.installer._package = package

    def should_process_command(self, command) -> bool:
        """Determines if the command should be processed by the plugin."""
        return isinstance(command, InstallerCommand)


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
        )

    def event_listener(
            self,
            event: cleo.events.console_command_event.ConsoleCommandEvent,
            event_name: str,
            dispatcher: cleo.events.event_dispatcher.EventDispatcher,
    ) -> None:
        if not self.env_manager.should_process_command(event.command):
            return

        event.io.write_line(
            f"Processing dependencies for environment: {self.env_manager.current_env}",
            verbosity=cleo.io.outputs.output.Verbosity.DEBUG,
        )

        self.env_manager.update_installer_package(event.command)