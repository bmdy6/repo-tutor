from .core import Service

@app.get('/hello')
async def hello():
    return Service().run(' hi ')

@click.command()
def cli():
    return hello()

if __name__ == '__main__':
    cli()
