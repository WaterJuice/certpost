# ----------------------------------------------------------------------------------------
#   argbuilder.py
#   -------------
#
#   A wrapper around Python's argparse using deferred execution. Arguments and commands
#   are collected first, then applied when parse() is called. This enables:
#
#   - Reusable arguments: add the same ArgsArgument instance to multiple commands
#   - Flexible ordering: define arguments in any order, not just top-down
#   - Command groups: organise subcommands under headings in --help output
#   - Collections: bundle related arguments for easy reuse across commands
#
#   Main classes:
#   - ArgsParser: entry point, call parse() to build argparse and get results
#   - ArgsCommand: defines a subcommand with its own arguments
#   - ArgsArgument: stores add_argument() params for later application
#   - ArgsCommandGroup: groups commands under a heading (cosmetic only)
#   - ArgsGroup: groups arguments under a heading in command help
#   - ArgsMutexGroup: mutually exclusive argument group
#   - ArgsCollection: reusable bundle of arguments
#
#   Licence: Unlicense - (c) 2026 WaterJuice
#
#   Version: 2026-03-08
# ----------------------------------------------------------------------------------------

# ----------------------------------------------------------------------------------------
#   Exports
# ----------------------------------------------------------------------------------------


__all__ = [
    "ArgsArgument",
    "ArgsCollection",
    "ArgsCommand",
    "ArgsCommandGroup",
    "ArgsGroup",
    "ArgsMutexGroup",
    "ArgsParser",
    "Namespace",
]

# ----------------------------------------------------------------------------------------
#   Settings
# ----------------------------------------------------------------------------------------

# pyright: reportPrivateUsage=false

# ----------------------------------------------------------------------------------------
#   Imports
# ----------------------------------------------------------------------------------------

import argparse
import sys
from argparse import Action
from argparse import Namespace
from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Sequence
from typing import Any
from typing import NoReturn
from typing import TypeVar
from typing import Union
from typing import cast
from typing import overload

# ----------------------------------------------------------------------------------------
#   Types
# ----------------------------------------------------------------------------------------


_T = TypeVar("_T")

# All argparse container types that can receive arguments
ParserLike = Union[
    argparse.ArgumentParser, argparse._ArgumentGroup, argparse._MutuallyExclusiveGroup
]

# Union of all item types that can be added to a parser/command
ArgsItem = Union["ArgsArgument", "ArgsGroup", "ArgsCollection", "ArgsMutexGroup"]

ArgsCompleteItem = Union[ArgsItem, "ArgsCommand", "ArgsCommandGroup"]

# ----------------------------------------------------------------------------------------
#   Private Base Class (must be defined before public classes that inherit from it)
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
class _BaseClass:
    """Base class providing common argument/command management functionality.

    Uses deferred execution: items are collected first, then applied to argparse
    when parse() is called. This allows flexible ordering and reuse of arguments.
    """

    # ------------------------------------------------------------------------------------
    def __init__(self, *, items: list[ArgsItem] | None = None):
        # Uses __all_items__ (dunder) to avoid name mangling, allowing subclass access
        self.__all_items__: list[ArgsCompleteItem] = []
        if items:
            self.add(*items)

    # ------------------------------------------------------------------------------------
    @overload
    def add_argument(
        self,
        *name_or_flags: str,
        action: str | type[Action] = ...,
        nargs: int | str = ...,
        const: Any = ...,
        default: Any = ...,
        type: Callable[[str], _T] | Callable[[str], _T] = ...,
        choices: Iterable[_T] = ...,
        required: bool = ...,
        help: str | None = ...,
        metavar: str | tuple[str, ...] | None = ...,
        dest: str | None = ...,
        version: str = ...,
        **kwargs: Any,
    ) -> "ArgsArgument":
        """
        Create and add a new argument.

        Takes the same parameters as `argparse.ArgumentParser.add_argument()`.

        Args:
            *name_or_flags: Argument name or option flags (e.g., "--verbose", "-v").
            action: How to handle the argument (store, store_true, count, etc.).
            nargs: Number of arguments to consume.
            const: Constant value for certain actions.
            default: Default value if argument not provided.
            type: Callable to convert the argument string.
            choices: Allowed values for the argument.
            required: Whether the argument is required.
            help: Help text for the argument.
            metavar: Display name in usage/help messages.
            dest: Attribute name in the resulting Namespace.
            version: Version string for version action.
            **kwargs: Additional keyword arguments passed to argparse.

        Returns:
            The created ArgsArgument instance, which can be reused in other commands.

        Example:
            ```python
            parser = ArgsParser("My app")
            cmd = parser.add_command("run")
            cmd.add_argument(
                "--verbose", "-v", action="store_true", help="Verbose output"
            )
            ```
        """
        ...

    @overload
    def add_argument(self) -> "ArgsArgument": ...

    def add_argument(self, *args: Any, **kwargs: Any) -> "ArgsArgument":
        new_argument = ArgsArgument(*args, **kwargs)
        self.__all_items__.append(new_argument)
        return new_argument

    # ------------------------------------------------------------------------------------
    def add_group(
        self, name: str, *, items: list[ArgsItem] | None = None
    ) -> "ArgsGroup":
        """
        Create and add an argument group for organised help display.

        Groups arguments under a heading in the --help output.

        Args:
            name: The group heading shown in help output.
            items: Optional list of arguments to add to this group.

        Returns:
            The created ArgsGroup instance.

        Example:
            ```python
            cmd = parser.add_command("run")
            output_group = cmd.add_group("Output Options")
            output_group.add_argument("--format", choices=["json", "text"])
            output_group.add_argument("--output", "-o", help="Output file")
            ```
        """
        new_group = ArgsGroup(name=name, items=items)
        self.__all_items__.append(new_group)
        return new_group

    # ------------------------------------------------------------------------------------
    def add_mutex_group(
        self, *, required: bool = False, items: list[ArgsItem] | None = None
    ) -> "ArgsMutexGroup":
        """
        Create and add a mutually exclusive argument group.

        Only one argument from this group can be used at a time.

        Args:
            required: If True, one of the arguments must be provided.
            items: Optional list of arguments to add to this group.

        Returns:
            The created ArgsMutexGroup instance.

        Example:
            ```python
            cmd = parser.add_command("output")
            mutex = cmd.add_mutex_group(required=True)
            mutex.add_argument("--json", action="store_true")
            mutex.add_argument("--xml", action="store_true")
            ```
        """
        mutex_group = ArgsMutexGroup(required=required)
        if items:
            mutex_group.add(*items)
        self.__all_items__.append(mutex_group)
        return mutex_group

    # ------------------------------------------------------------------------------------
    def add(self, *items: ArgsItem) -> None:
        """
        Add existing items (arguments, groups, collections) to this container.

        Use this to reuse ArgsArgument or ArgsCollection instances across
        multiple commands.

        Args:
            *items: One or more items to add.

        Example:
            ```python
            verbose = ArgsArgument("--verbose", "-v", action="store_true")
            cmd1.add(verbose)
            cmd2.add(verbose)  # Same argument in both commands
            ```
        """
        for item in items:
            self.__all_items__.append(item)

    # ------------------------------------------------------------------------------------
    def _add_item(self, item: ArgsCompleteItem) -> None:
        """Internal method to add an item to the parser."""
        self.__all_items__.append(item)

    # ------------------------------------------------------------------------------------
    def __add_to_parser__(self, parser: ParserLike) -> None:
        """Apply all collected items to the actual argparse parser.

        This is the deferred execution point where our wrapper objects
        are converted into real argparse objects.
        """
        sub_parsers = None
        for item in self.__all_items__:
            if isinstance(item, ArgsCommand):
                # Lazily create subparsers container on first command
                if not sub_parsers:
                    assert isinstance(parser, argparse.ArgumentParser)
                    sub_parsers = parser.add_subparsers(
                        title="commands",
                        dest="command",
                        required=False,
                        metavar="command",
                    )
                item.__add_to_sub_parser__(sub_parsers)
            else:
                item.__add_to_parser__(parser)


# ----------------------------------------------------------------------------------------
#   Public Classes
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
class ArgsParser(_BaseClass):
    """
    Main entry point for building CLI applications.

    Create a parser, add commands and arguments, then call `parse()` to
    process command-line arguments.

    Args:
        prog: Program name for usage/help output (optional).
        description: Description shown at the top of --help output (optional).
        version: Version string; if set, adds --version option (optional).
        default_command: Default command when user doesn't specify one (optional).

    Attributes:
        prog (str | None): Can be set after initialisation, before parse().
        description (str | None): Can be set after initialisation, before parse().
        version (str | None): Can be set after initialisation, before parse().
        default_command (str | None): Can be set after initialisation, before parse().

    Example:
        ```python
        parser = ArgsParser("My CLI application")

        # Can also set attributes directly
        parser.prog = "mycli"
        parser.version = "1.0.0"
        parser.default_command = "help"

        # Add global arguments
        parser.add_argument("--verbose", "-v", action="store_true")

        # Add commands
        init = parser.add_command("init", help="Initialise project")
        init.add_argument("--force", action="store_true")

        # Parse and use results
        args = parser.parse()
        if args.command == "init":
            initialise(force=args.force)
        ```
    """

    prog: str | None
    """Program name shown in usage/help output."""

    description: str | None
    """Description shown at top of help output."""

    epilog: str | None
    """Text shown at the bottom of help output."""

    version: str | None
    """Version string; if set, adds --version option."""

    default_command: str | None
    """Default command when none specified by user."""

    # ------------------------------------------------------------------------------------
    def __init__(
        self,
        prog: str | None = None,
        description: str | None = None,
        version: str | None = None,
        default_command: str | None = None,
        epilog: str | None = None,
    ):
        """
        Initialise the helper with program metadata and defaults.

        Parameters:
            prog: Program name for usage output.
            description: Top-level description for help.
            version: Version string; if provided, a --version option is added.
            default_command: Default command to use when none is specified.
                If set and user doesn't provide a command, this one is used.
                If not set and user doesn't provide a command, help is shown.
        """

        super().__init__()
        self.description = description
        self.epilog = epilog
        self.prog = prog
        self.version = version
        self.default_command = default_command
        self._common_options_first = False
        self.__command_groups: list[ArgsCommandGroup] = []
        self.__common_collection__: ArgsCollection | None = None
        self.__parser: argparse.ArgumentParser | None = None

    # ------------------------------------------------------------------------------------
    def add_command(
        self,
        name: str,
        *,
        items: list[ArgsItem] | None = None,
        help: str | None = None,
        description: str | None = None,
        exclude_common: bool = False,
    ) -> "ArgsCommand":
        """
        Create and add a new subcommand.

        Args:
            name: The command name used on the command line.
            items: Optional list of arguments/groups to add to this command.
            help: Short help text shown in parent's command list.
            description: Longer description shown in command's own --help.
                If only one of help/description is provided, it's used for both.
            exclude_common: If True, excludes common options from this command.

        Returns:
            The created ArgsCommand instance.

        Example:
            ```python
            parser = ArgsParser("My app")
            cmd = parser.add_command("init", help="Initialise project")
            cmd.add_argument("--force", action="store_true")

            # Command without common options
            special = parser.add_command("special", exclude_common=True)
            ```
        """
        new_command = ArgsCommand(
            name=name, items=items, help=help, description=description
        )
        if self.__common_collection__ and not exclude_common:
            if self._common_options_first:
                # Insert at the beginning of items list
                new_command._prepend_item(self.__common_collection__)
            else:
                # Store for later application at the end
                new_command._common_collection = self.__common_collection__
        self.__all_items__.append(new_command)
        return new_command

    # ------------------------------------------------------------------------------------
    def create_common_collection(
        self, *, items: list[ArgsItem] | None = None, options_first: bool = False
    ) -> "ArgsCollection":
        """
        Create a reusable collection automatically added to every command.

        Use this when you have arguments that should be present on all commands
        (for example `--verbose`). The returned collection behaves like any other
        `ArgsCollection` and can be added to additional commands manually if
        needed.

        Note:
            To exclude common options from specific commands, use the
            `exclude_common=True` parameter when calling `add_command()`.

        Args:
            items: Optional list of pre-defined arguments/groups to seed the
                collection with.
            options_first: If True, common options appear at the beginning of
                each command's help output. If False (default), they appear at
                the end.

        Returns:
            The collection instance that will be appended to each command added
            to this parser (unless excluded via `exclude_common=True`).

        Example:
            ```python
            parser = ArgsParser("My app")
            common = parser.create_common_collection(options_first=True)
            common.add_argument("--verbose", "-v", action="count")

            deploy = parser.add_command("deploy")
            test = parser.add_command("test")
            # Both commands now accept --verbose automatically at the beginning

            # Exclude common options from a specific command
            special = parser.add_command("special", exclude_common=True)
            # special command will NOT have --verbose

            args = parser.parse()
            ```
        """

        self._common_options_first = options_first
        self.__common_collection__ = ArgsCollection(items=items)
        return self.__common_collection__

    # ------------------------------------------------------------------------------------
    def add_command_group(
        self, name: str, *, description: str | None = None
    ) -> "ArgsCommandGroup":
        """
        Create a command group for organising commands in help output.

        Command groups are purely cosmetic - they organise how commands
        appear in --help but don't affect parsing behaviour.

        Args:
            name: The group heading shown in help output.
            description: Optional description shown below the heading.

        Returns:
            The created ArgsCommandGroup instance.

        Example:
            ```python
            parser = ArgsParser("My app")

            basic = parser.add_command_group("Basic Commands")
            basic.add_command("init", help="Initialise project")
            basic.add_command("status", help="Show status")

            advanced = parser.add_command_group("Advanced Commands")
            advanced.add_command("migrate", help="Run migrations")
            ```
        """
        group = ArgsCommandGroup(name=name, description=description, parent=self)
        self.__command_groups.append(group)
        return group

    # ------------------------------------------------------------------------------------
    def _get_all_command_names(self) -> set[str]:
        """Get all registered command names."""
        names: set[str] = set()
        # Commands added directly to parser
        for item in self.__all_items__:
            if isinstance(item, ArgsCommand):
                names.add(item._command_name)
        # Commands added via command groups
        for group in self.__command_groups:
            for cmd in group.commands:
                names.add(cmd._command_name)
        return names

    # ------------------------------------------------------------------------------------
    def _reorder_args(self, argv: list[str]) -> list[str]:
        """Move command to front of argument list if found.

        Allows commands to appear anywhere in the argument list, not just
        at the beginning. For example: `mytool --verbose run --force`
        becomes `mytool run --verbose --force`.
        """
        command_names = self._get_all_command_names()
        if not command_names:
            return argv

        # Find the first argument that matches a command name
        command_index = None
        for i, arg in enumerate(argv):
            if arg in command_names:
                command_index = i
                break

        # If command found and not already at front, move it
        if command_index is not None and command_index > 0:
            command = argv[command_index]
            return [command] + argv[:command_index] + argv[command_index + 1 :]

        return argv

    # ------------------------------------------------------------------------------------
    def _print_help_all(self, parser: argparse.ArgumentParser) -> None:
        """Print markdown-formatted help for main parser and all commands."""
        prog = self.prog or sys.argv[0]

        # Print main help
        print(f"## `{prog}`\n")
        print("```")
        print(parser.format_help())
        print("```\n")

        # Find and print help for each command
        subparsers_group = parser._subparsers  # pyright: ignore[reportAttributeAccessIssue]
        if subparsers_group is None:
            return

        for action in subparsers_group._actions:
            if isinstance(action, argparse._SubParsersAction):
                parser_map = cast(
                    "dict[str, argparse.ArgumentParser]",
                    action._name_parser_map,  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
                )
                for name, subparser in parser_map.items():
                    print(f"## `{prog} {name}`\n")
                    print("```")
                    print(subparser.format_help())
                    print("```\n")

    # ------------------------------------------------------------------------------------
    def parse(self, argv: list[str] | None = None) -> Namespace:
        """Build the argument parser and parse command-line arguments.

        This triggers deferred execution: all collected arguments and commands
        are applied to create the actual argparse structure, then arguments
        are parsed.

        Commands can appear anywhere in the argument list - they will be
        automatically moved to the front before parsing.

        Args:
            argv: Optional list of argument strings to parse. If not provided,
                defaults to sys.argv[1:] (command-line arguments).

        Returns:
            Namespace object with parsed argument values. Access the selected
            command name via the `command` attribute.

        Example:
            ```python
            # Parse command-line arguments (default behaviour)
            args = parser.parse()
            print(args.command)   # "init", "run", etc.
            print(args.verbose)   # True/False

            # Parse custom arguments
            args = parser.parse(argv=["init", "--config", "app.yml"])
            print(args.command)   # "init"
            ```
        """
        # Use provided argv or default to sys.argv[1:]
        if argv is None:
            argv = sys.argv[1:]

        # Build command group metadata for the custom help formatter
        command_groups: dict[str, list[tuple[str, str | None]]] = {}
        group_descriptions: dict[str, str | None] = {}

        for group in self.__command_groups:
            group_descriptions[group.name] = group.description
            command_groups[group.name] = [
                (cmd._command_name, cmd._help) for cmd in group.commands
            ]

        # Factory function to inject group metadata into formatter
        # (argparse only passes prog to formatter_class, so we use a closure)
        def formatter_class(prog: str, **kwargs: Any) -> _GroupedCommandsHelpFormatter:
            return _GroupedCommandsHelpFormatter(
                prog,
                command_groups=command_groups,
                group_descriptions=group_descriptions,
                **kwargs,
            )

        parser = argparse.ArgumentParser(
            prog=self.prog,
            description=self.description,
            epilog=self.epilog,
            formatter_class=formatter_class,
        )

        if self.version:
            parser.add_argument(
                "--version", action=_RawVersionAction, version=self.version
            )

        self.__add_to_parser__(parser)

        # Handle --help-all before normal parsing
        if "--help-all" in argv:
            self._print_help_all(parser)
            sys.exit(0)

        # Reorder arguments to allow command anywhere in the argument list
        reordered_argv = self._reorder_args(argv)

        # Handle missing command when commands exist
        command_names = self._get_all_command_names()
        if command_names:
            # Check if a command was provided
            has_command = any(arg in command_names for arg in reordered_argv)

            if not has_command:
                # Check if user is asking for help or version (let argparse handle these)
                is_help = "--help" in reordered_argv or "-h" in reordered_argv
                is_version = (
                    "--version" in reordered_argv or "--license" in reordered_argv
                )

                if is_help or is_version:
                    # User wants help or version - let argparse show them
                    pass
                elif self.default_command:
                    # Inject default command at the front
                    reordered_argv = [self.default_command] + reordered_argv
                else:
                    # No command and no default: show help and exit
                    parser.print_help()
                    sys.exit(0)

        args = parser.parse_args(reordered_argv)
        self.__parser = parser
        return args

    # ------------------------------------------------------------------------------------
    def error(self, msg: str) -> NoReturn:
        """Print an error message and exit, using the same format as argparse.

        This method can only be called after parse() has been invoked, as the
        underlying ArgumentParser is created during parsing.

        Args:
            msg: The error message to display.

        Raises:
            RuntimeError: If called before parse() has been run.

        Example:
            ```python
            args = parser.parse()
            if not args.config:
                parser.error("--config is required")
            ```
        """
        if self.__parser is None:
            raise RuntimeError(
                "parser.error() cannot be called before parse() has been executed. "
                "Call parse() first to initialise the argument parser."
            )
        self.__parser.error(msg)

    # ------------------------------------------------------------------------------------
    @overload
    @classmethod
    def new_argument(
        cls,
        *name_or_flags: str,
        action: str | type[Action] = ...,
        nargs: int | str = ...,
        const: Any = ...,
        default: Any = ...,
        type: Callable[[str], _T] | Callable[[str], _T] = ...,
        choices: Iterable[_T] = ...,
        required: bool = ...,
        help: str | None = ...,
        metavar: str | tuple[str, ...] | None = ...,
        dest: str | None = ...,
        version: str = ...,
        **kwargs: Any,
    ) -> "ArgsArgument": ...

    @overload
    @classmethod
    def new_argument(cls) -> "ArgsArgument": ...

    @classmethod
    def new_argument(cls, *args: Any, **kwargs: Any) -> "ArgsArgument":
        """
        Convenience constructor for `ArgsArgument`.

        Mirrors `ArgsArgument(*args, **kwargs)` so callers can create reusable
        arguments without importing the class directly.
        """
        return ArgsArgument(*args, **kwargs)

    # ------------------------------------------------------------------------------------
    @classmethod
    def new_collection(cls, items: list[ArgsItem] | None = None) -> "ArgsCollection":
        """
        Convenience constructor for `ArgsCollection`.

        Args:
            items: Optional list of arguments or groups to seed the collection.

        Returns:
            A new `ArgsCollection` instance.
        """
        return ArgsCollection(items=items)

    # ------------------------------------------------------------------------------------
    @classmethod
    def new_group(
        cls, name: str, *, items: list[ArgsItem] | None = None
    ) -> "ArgsGroup":
        """
        Convenience constructor for `ArgsGroup`.

        Args:
            name: Heading shown in command help.
            items: Optional list of arguments or nested groups to add.

        Returns:
            A new `ArgsGroup` instance.
        """
        return ArgsGroup(name=name, items=items)

    # ------------------------------------------------------------------------------------
    @classmethod
    def new_mutex_group(
        cls, *, required: bool = False, items: list[ArgsItem] | None = None
    ) -> "ArgsMutexGroup":
        """
        Convenience constructor for `ArgsMutexGroup`.

        Args:
            required: If True, one of the arguments must be provided.
            items: Optional list of mutually exclusive arguments to add.

        Returns:
            A new `ArgsMutexGroup` instance.
        """
        return ArgsMutexGroup(required=required, items=items)

    # ------------------------------------------------------------------------------------
    @classmethod
    def new_command(
        cls,
        name: str,
        *,
        items: list[ArgsItem] | None = None,
        help: str | None = None,
        description: str | None = None,
    ) -> "ArgsCommand":
        """
        Convenience constructor for `ArgsCommand`.

        Note:
            This creates a standalone command not attached to any parser.
            The `exclude_common` parameter is not available here since
            common collections are managed by `ArgsParser`.

        Args:
            name: Command name shown on the CLI.
            items: Optional list of arguments/groups to add to the command.
            help: Short summary displayed in parent command lists.
            description: Detailed description for the command's own help.

        Returns:
            A new `ArgsCommand` instance.
        """
        return ArgsCommand(name=name, items=items, help=help, description=description)


# ----------------------------------------------------------------------------------------
class ArgsArgument:
    """
    A reusable command-line argument definition.

    Wraps the parameters for `argparse.ArgumentParser.add_argument()` so they
    can be stored and applied later. The same ArgsArgument instance can be
    added to multiple commands for reuse.

    Args:
        *name_or_flags: Argument name or option flags (e.g., "filename", "--verbose",
            "-v").
        action: How to handle the argument (store, store_true, count, etc.).
        nargs: Number of arguments to consume.
        const: Constant value for certain actions.
        default: Default value if argument not provided.
        type: Callable to convert the argument string.
        choices: Allowed values for the argument.
        required: Whether the argument is required.
        help: Help text for the argument.
        metavar: Display name in usage/help messages.
        dest: Attribute name in the resulting Namespace.
        version: Version string for version action.
        **kwargs: Additional keyword arguments passed to argparse.

        Example:
            ```python
            # Create reusable argument
            verbose = ArgsArgument(
                "--verbose", "-v", action="store_true", help="Verbose mode"
            )

        # Use in multiple commands
        cmd1.add(verbose)
        cmd2.add(verbose)
        ```
    """

    @overload
    def __init__(
        self,
        *name_or_flags: str,
        action: str | type[Action] = ...,
        nargs: int | str = ...,
        const: Any = ...,
        default: Any = ...,
        type: Callable[[str], _T] | Callable[[str], _T] = ...,
        choices: Iterable[_T] = ...,
        required: bool = ...,
        help: str | None = ...,
        metavar: str | tuple[str, ...] | None = ...,
        dest: str | None = ...,
        version: str = ...,
        **kwargs: Any,
    ) -> None: ...

    @overload
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.__args = args
        self.__kwargs = kwargs

    # ------------------------------------------------------------------------------------
    @property
    def args(self) -> tuple[Any, ...]:
        """The positional arguments (name/flags) for this argument."""
        return self.__args

    # ------------------------------------------------------------------------------------
    @property
    def kwargs(self) -> dict[str, Any]:
        """The keyword arguments (action, help, etc.) for this argument."""
        return self.__kwargs

    # ------------------------------------------------------------------------------------
    def clone(self, **kwargs: Any) -> "ArgsArgument":
        """
        Clone this argument with modified keyword arguments.

        Returns a new ArgsArgument instance with the same positional arguments
        (name/flags) and keyword arguments as this one, but with specified
        keyword arguments overridden.

        Args:
            **kwargs: Keyword arguments to override or add. These will replace
                any matching kwargs from the original argument.

        Returns:
            A new ArgsArgument instance with the modifications applied.

        Example:
            ```python
            # Create base argument
            dir_arg = ArgsArgument(
                "--dir", "-d",
                help="Directory to process"
            )

            # Create required variant
            dir_required = dir_arg.clone(required=True)

            # Create variant with different help text
            dir_custom = dir_arg.clone(
                help="Custom help text",
                metavar="PATH"
            )
            ```
        """
        # Create a new dict with existing kwargs, then update with modifications
        new_kwargs = self.__kwargs.copy()
        new_kwargs.update(kwargs)
        return ArgsArgument(*self.__args, **new_kwargs)

    # ------------------------------------------------------------------------------------
    def __add_to_parser__(self, parser: ParserLike) -> None:
        parser.add_argument(*self.__args, **self.__kwargs)


# ----------------------------------------------------------------------------------------
class ArgsCommand(_BaseClass):
    """
    A subcommand in the CLI.

    Commands can have their own arguments, argument groups, and even nested
    subcommands.

    Args:
        name: The command name used on the command line.
        items: Optional list of arguments/groups to add to this command.
        help: Short help text shown in parent's command list.
        description: Longer description shown in command's own --help.
            If only one of help/description is provided, it's used for both.

    Example:
        ```python
        parser = ArgsParser("My app")
        cmd = parser.add_command("deploy", help="Deploy the application")
        cmd.add_argument("--env", choices=["dev", "prod"], required=True)
        cmd.add_argument("--dry-run", action="store_true")
        ```
    """

    # ------------------------------------------------------------------------------------
    def __init__(
        self,
        name: str,
        *,
        items: list[ArgsItem] | None = None,
        help: str | None = None,
        description: str | None = None,
    ):
        super().__init__()
        self._command_name = name
        self._help = help or description
        self._description = description or help
        self._common_collection: ArgsCollection | None = None
        if items:
            self.add(*items)

    # ------------------------------------------------------------------------------------
    def _prepend_item(self, item: ArgsItem) -> None:
        """Add an item at the beginning of the items list."""
        self.__all_items__.insert(0, item)

    # ------------------------------------------------------------------------------------
    def __add_to_sub_parser__(
        self, sub_parsers: "argparse._SubParsersAction[argparse.ArgumentParser]"
    ) -> None:
        command_parser = sub_parsers.add_parser(
            name=self._command_name,
            description=self._description,
            help=self._help,
            add_help=False,
            formatter_class=_FixedHelpFormatter,
        )
        command_parser.add_argument(
            "--help", "-h", action="help", help=argparse.SUPPRESS
        )
        for item in self.__all_items__:
            item.__add_to_parser__(command_parser)
        # Apply common options at the end if they were deferred
        if self._common_collection:
            self._common_collection.__add_to_parser__(command_parser)


# ----------------------------------------------------------------------------------------
class ArgsCollection(_BaseClass):
    """
    A reusable collection of arguments that can be added to multiple commands.

    Use collections to bundle related arguments that should be available
    in multiple commands.

    Example:
        ```python
        # Create a collection of common output options
        output_opts = ArgsCollection()
        output_opts.add_argument("--format", choices=["json", "text", "yaml"])
        output_opts.add_argument("--output", "-o", help="Output file")
        output_opts.add_argument("--quiet", "-q", action="store_true")

        # Add to multiple commands
        list_cmd.add(output_opts)
        show_cmd.add(output_opts)
        export_cmd.add(output_opts)
        ```
    """

    ...


# ----------------------------------------------------------------------------------------
class ArgsCommandGroup:
    """
    A group of commands for organisational display in help output.

    This is purely cosmetic - it affects how commands appear in --help
    but doesn't change parsing behaviour. Commands are grouped under
    headings instead of being listed in one flat section.

    Note:
        Create command groups via `ArgsParser.add_command_group()`, not directly.

    Args:
        name: The group heading shown in help output.
        description: Optional description shown below the heading.
        parent: The parent ArgsParser (set automatically).

    Example:
        ```python
        parser = ArgsParser("My app")

        # Create groups for organised help
        basic = parser.add_command_group(
            "Basic Commands", description="Common operations"
        )
        basic.add_command("init", help="Initialise project")
        basic.add_command("status", help="Show project status")

        advanced = parser.add_command_group("Advanced Commands")
        advanced.add_command("migrate", help="Run database migrations")
        ```
    """

    # ------------------------------------------------------------------------------------
    def __init__(
        self,
        name: str,
        *,
        description: str | None = None,
        parent: ArgsParser | None = None,
    ):
        self.__group_name = name
        self.__description = description
        self.__commands: list[ArgsCommand] = []
        self.__parent = parent

    # ------------------------------------------------------------------------------------
    @property
    def name(self) -> str:
        """The group heading name."""
        return self.__group_name

    # ------------------------------------------------------------------------------------
    @property
    def description(self) -> str | None:
        """Optional description shown below the heading."""
        return self.__description

    # ------------------------------------------------------------------------------------
    @property
    def commands(self) -> list[ArgsCommand]:
        """List of commands in this group."""
        return self.__commands

    # ------------------------------------------------------------------------------------
    def add_command(
        self,
        name: str,
        *,
        items: list[ArgsItem] | None = None,
        help: str | None = None,
        description: str | None = None,
        exclude_common: bool = False,
    ) -> ArgsCommand:
        """Add a command to this group.

        Args:
            name: The command name used on the command line.
            items: Optional list of arguments/groups to add to this command.
            help: Short help text shown in parent's command list.
            description: Longer description shown in command's own --help.
            exclude_common: If True, excludes common options from this command.

        Returns:
            The created ArgsCommand instance.
        """
        new_command = ArgsCommand(
            name=name, items=items, help=help, description=description
        )
        self.__commands.append(new_command)
        if self.__parent:
            self.__parent._add_item(new_command)
            if self.__parent.__common_collection__ and not exclude_common:
                if self.__parent._common_options_first:
                    # Insert at the beginning of items list
                    new_command._prepend_item(self.__parent.__common_collection__)
                else:
                    # Store for later application at the end
                    new_command._common_collection = self.__parent.__common_collection__
        return new_command

    # ------------------------------------------------------------------------------------
    def __add_to_parser__(self, _parser: ParserLike) -> None:
        # Commands are added via parent, this is just for interface compatibility
        pass


# ----------------------------------------------------------------------------------------
class ArgsGroup(_BaseClass):
    """
    A named group of arguments for organisational display in help output.

    Groups arguments under a heading in the command's --help output.

    Args:
        name: The group heading shown in help output.
        items: Optional list of arguments to add to this group.

    Example:
        ```python
        cmd = parser.add_command("run")

        # Group related arguments
        output = cmd.add_group("Output Options")
        output.add_argument("--format", choices=["json", "text"])
        output.add_argument("--output", "-o", help="Output file")

        debug = cmd.add_group("Debug Options")
        debug.add_argument("--verbose", "-v", action="store_true")
        debug.add_argument("--trace", action="store_true")
        ```
    """

    # ------------------------------------------------------------------------------------
    def __init__(self, name: str, *, items: list[ArgsItem] | None = None):
        super().__init__()
        self.__group_name = name
        if items:
            self.add(*items)

    # ------------------------------------------------------------------------------------
    def __add_to_parser__(self, parser: ParserLike) -> None:
        group_parser = parser.add_argument_group(title=self.__group_name)
        for item in self.__all_items__:
            item.__add_to_parser__(group_parser)


# ----------------------------------------------------------------------------------------
class ArgsMutexGroup(_BaseClass):
    """
    A mutually exclusive group of arguments.

    Only one argument from this group can be specified at a time.

    Args:
        required: If True, one of the arguments must be provided.
        items: Optional list of arguments to add to this group.

    Example:
        ```python
        cmd = parser.add_command("output")

        # User must choose exactly one format
        format_group = cmd.add_mutex_group(required=True)
        format_group.add_argument("--json", action="store_true", help="JSON output")
        format_group.add_argument("--xml", action="store_true", help="XML output")
        format_group.add_argument("--csv", action="store_true", help="CSV output")

        # Optional mutex: at most one can be specified
        verbosity = cmd.add_mutex_group()
        verbosity.add_argument("--quiet", "-q", action="store_true")
        verbosity.add_argument("--verbose", "-v", action="store_true")
        ```
    """

    # ------------------------------------------------------------------------------------
    def __init__(self, *, required: bool = False, items: list[ArgsItem] | None = None):
        super().__init__()
        if items:
            self.add(*items)
        self.__mutex_group_required = required

    # ------------------------------------------------------------------------------------
    def __add_to_parser__(self, parser: ParserLike) -> None:
        mutex_group_parser = parser.add_mutually_exclusive_group(
            required=self.__mutex_group_required
        )
        for item in self.__all_items__:
            item.__add_to_parser__(mutex_group_parser)


# ----------------------------------------------------------------------------------------
#   Private Classes (internal implementation details)
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
class _FixedHelpFormatter(argparse.HelpFormatter):
    """HelpFormatter with Python 3.12 double metavar fix and newline preservation.

    Python 3.12 shows: --value VALUE, -v VALUE
    This fixes it to: --value, -v VALUE
    (Fixed upstream in Python 3.13+)

    Also preserves explicit newlines in description and help text.
    """

    def _fill_text(self, text: str, width: int, indent: str) -> str:
        """Fill text while preserving explicit line breaks.

        Each paragraph (separated by newlines) is wrapped individually to
        *width*. Empty lines are preserved as paragraph separators.
        """
        if "\n" not in text:
            return super()._fill_text(text, width, indent)
        paragraphs = text.split("\n")
        filled: list[str] = []
        for para in paragraphs:
            if not para.strip():
                filled.append("")
            else:
                filled.append(super()._fill_text(para, width, indent).rstrip("\n"))
        return "\n".join(filled) + "\n"

    def _split_lines(self, text: str, width: int) -> list[str]:  # type: ignore[override]
        """Split lines while preserving explicit newlines.

        This handles the help text for individual options.
        """
        lines: list[str] = []
        for segment in text.split("\n"):
            if segment == "":
                lines.append("")  # keep blank lines
            else:
                lines.extend(super()._split_lines(segment, width))
        return lines

    def _format_action_invocation(self, action: Action) -> str:
        if sys.version_info < (3, 13) and action.option_strings:
            if action.nargs != 0:
                default = self._get_default_metavar_for_optional(action)
                args_string = self._format_args(action, default)
                return ", ".join(action.option_strings) + " " + args_string
        return super()._format_action_invocation(action)


# ----------------------------------------------------------------------------------------
class _GroupedCommandsHelpFormatter(_FixedHelpFormatter):
    """Custom formatter that displays subcommands grouped under headings."""

    def __init__(
        self,
        prog: str,
        indent_increment: int = 2,
        max_help_position: int = 24,
        width: int | None = None,
        command_groups: dict[str, list[tuple[str, str | None]]] | None = None,
        group_descriptions: dict[str, str | None] | None = None,
        **kwargs: Any,
    ):
        super().__init__(prog, indent_increment, max_help_position, width, **kwargs)
        self._command_groups = command_groups or {}
        self._group_descriptions = group_descriptions or {}

    def _format_actions_usage(
        self,
        actions: Iterable[Action],
        groups: Iterable[argparse._MutuallyExclusiveGroup],
    ) -> str:
        return super()._format_actions_usage(actions, groups)

    def _metavar_formatter(
        self, action: Action, default_metavar: str
    ) -> Callable[[int], tuple[str, ...]]:
        return super()._metavar_formatter(action, default_metavar)

    def _format_action(self, action: Action) -> str:
        # Intercept subparser action to control how commands are displayed
        if isinstance(action, argparse._SubParsersAction):
            return self._format_grouped_subparsers(
                cast("argparse._SubParsersAction[argparse.ArgumentParser]", action)
            )
        # Cast needed: isinstance check leaves type as Action | _SubParsersAction[Unknown]
        return super()._format_action(action)

    def _format_grouped_subparsers(
        self,
        action: "argparse._SubParsersAction[argparse.ArgumentParser]",
    ) -> str:
        """Format subcommands organised under group headings."""
        parts: list[str] = []
        width = self._width or 80
        help_position = self._max_help_position
        name_indent = "  "
        help_indent = " " * help_position

        # Build dict of all subparsers with their help text
        # (used to track which commands aren't in any group)
        subparsers: dict[str, str | None] = {}
        for name in action._name_parser_map:
            help_text: str | None = None
            for choice_action in action._choices_actions:
                if choice_action.dest == name:
                    help_text = choice_action.help
                    break
            subparsers[name] = help_text

        # Python 3.14+ supports coloured terminal output via _theme
        theme: Any = getattr(self, "_theme", None)
        has_colors = theme is not None

        if has_colors:
            heading_style: str = getattr(theme, "heading", "")
            action_style: str = getattr(theme, "action", "")
            reset_style: str = getattr(theme, "reset", "")
        else:
            heading_style = action_style = reset_style = ""

        def format_command(
            name: str, help_text: str | None, *, coloured_name: str
        ) -> str:
            # Align help text at help_position and wrap long descriptions
            visible_name_len = len(name_indent) + len(name)

            if not help_text:
                return f"{name_indent}{coloured_name}\n"

            wrapped_help = self._split_lines(help_text, max(1, width - help_position))
            if not wrapped_help:
                return f"{name_indent}{coloured_name}\n"

            lines: list[str] = []
            if visible_name_len >= help_position:
                lines.append(f"{name_indent}{coloured_name}\n")
                lines.append(f"{help_indent}{wrapped_help[0]}\n")
            else:
                padding = " " * (help_position - visible_name_len)
                lines.append(
                    f"{name_indent}{coloured_name}{padding}{wrapped_help[0]}\n"
                )

            for line in wrapped_help[1:]:
                lines.append(f"{help_indent}{line}\n")

            return "".join(lines)

        def format_group_description(text: str) -> str:
            wrapped = self._split_lines(text, max(1, width - len(name_indent)))
            return "".join(f"{name_indent}{line}\n" for line in wrapped)

        # Format each command group
        for group_name, commands in self._command_groups.items():
            if not commands:
                continue

            parts.append(f"\n{heading_style}{group_name}:{reset_style}\n")

            group_desc = self._group_descriptions.get(group_name)
            if group_desc:
                parts.append(format_group_description(group_desc))
                parts.append("\n")

            for cmd_name, cmd_help in commands:
                coloured_name = (
                    f"{action_style}{cmd_name}{reset_style}" if has_colors else cmd_name
                )
                parts.append(
                    format_command(cmd_name, cmd_help, coloured_name=coloured_name)
                )
                # Mark as processed
                subparsers.pop(cmd_name, None)

        # Commands not assigned to any group go under generic "Commands:" heading
        if subparsers:
            for name, help_text in subparsers.items():
                coloured_name = (
                    f"{action_style}{name}{reset_style}" if has_colors else name
                )
                parts.append(
                    format_command(name, help_text, coloured_name=coloured_name)
                )

        return "".join(parts)


# ----------------------------------------------------------------------------------------
class _RawVersionAction(argparse._VersionAction):
    """Version action that preserves newlines in version strings."""

    version: str | None

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        parser_version: Any = getattr(parser, "version", None)
        version_value = self.version or parser_version or parser.prog or ""
        version_str = str(version_value)
        if not version_str.endswith("\n"):
            version_str += "\n"
        parser._print_message(version_str, sys.stdout)
        parser.exit()
