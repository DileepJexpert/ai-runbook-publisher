from __future__ import annotations
import click
from reviewer.engine import IdfcCoderEngine
from reviewer.models import ReviewMode
from reviewer.orchestrator import ReviewOrchestrator
@click.command()
@click.option('--repo', required=True, type=click.Path(exists=True, file_okay=False))
@click.option('--base', required=True)
@click.option('--head', required=True)
@click.option('--review-mode', type=click.Choice(['baseline','guided','both']), default='guided')
@click.option('--engine', type=click.Choice(['idfc-coder']), default='idfc-coder')
@click.option('--output-root', default='output/reviews')
def main(repo, base, head, review_mode, engine, output_root):
    results=ReviewOrchestrator(IdfcCoderEngine()).run(repo,base,head,ReviewMode(review_mode),output_root)
    click.echo('Completed: ' + ', '.join(x.value for x in results))
if __name__ == '__main__': main()
