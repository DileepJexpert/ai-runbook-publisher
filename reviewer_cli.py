from __future__ import annotations
import click
from reviewer.engine import IdfcCoderEngine
from reviewer.models import ReviewMode
from reviewer.orchestrator import ReviewOrchestrator
from reviewer.pr_resolver import resolve_url
@click.command()
@click.option('--repo', required=True, type=click.Path(exists=True, file_okay=False))
@click.option('--base')
@click.option('--head')
@click.option('--url')
@click.option('--review-mode', type=click.Choice(['baseline','guided','both']), default='guided')
@click.option('--engine', type=click.Choice(['idfc-coder']), default='idfc-coder')
@click.option('--coder-mode', type=click.Choice(['prompt','stdin','interactive']), default='prompt')
@click.option('--output-root', default='output/reviews')
@click.option('--depth', type=click.Choice(['fast','standard','deep']), default='standard')
@click.option('--no-fetch', is_flag=True)
def main(repo, base, head, url, review_mode, engine, coder_mode, output_root, depth, no_fetch):
    if url:
        resolved=resolve_url(url, base)
        if not resolved: raise click.ClickException('Could not resolve source and target from URL; pass --base and --head.')
        base, head=resolved
    if not base or not head: raise click.ClickException('--base and --head are required unless supported --url is used.')
    results=ReviewOrchestrator(IdfcCoderEngine(input_mode=coder_mode)).run(repo,base,head,ReviewMode(review_mode),output_root,fetch=not no_fetch,depth=depth)
    for mode, result in results.items(): click.echo(f'Outcome: {result.outcome.value}\nOutput: {output_root}\nMode: {mode.value}')
if __name__ == '__main__': main()
