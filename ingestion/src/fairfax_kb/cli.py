"""
Command-line entrypoint for running ingestion phases manually during
development. Wire this up as each phase becomes implemented.

Examples (once implemented):
  python -m fairfax_kb.cli discover --view-id 13
  python -m fairfax_kb.cli fetch-documents --meeting-id 42
  python -m fairfax_kb.cli extract --meeting-id 42
"""
import click


@click.group()
def cli():
    pass


@cli.command()
@click.option("--view-id", required=True, help="Granicus view_id to discover meetings for")
def discover(view_id):
    """Phase 1: discover meetings for a view_id and store them."""
    click.echo(f"TODO: implement discovery for view_id={view_id} (see scraper/granicus.py)")


if __name__ == "__main__":
    cli()
