"""
Main CLI application for CodeWiki using Click framework.
"""

import sys
import click

from codewiki import __version__


@click.group()
@click.version_option(version=__version__, prog_name="CodeWiki CLI")
@click.pass_context
def cli(ctx):
    """
    CodeWiki: Analyze codebases and render documentation as HTML.

    Supports Python, Java, JavaScript, TypeScript, C, C++, C#, and more.
    """
    ctx.ensure_object(dict)


@cli.command()
def version():
    """Display version information."""
    click.echo(f"CodeWiki CLI v{__version__}")


from codewiki.cli.commands.analyze import analyze_command
from codewiki.cli.commands.html import html_command

cli.add_command(analyze_command, name="analyze")
cli.add_command(html_command, name="html")


def main():
    """Entry point for the CLI."""
    try:
        cli(obj={})
    except KeyboardInterrupt:
        click.echo("\n\nInterrupted by user", err=True)
        sys.exit(130)
    except Exception as e:
        click.secho(f"\n✗ Unexpected error: {e}", fg="red", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
