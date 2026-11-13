from .util import clean

class Service:
    """Serve normalized values."""
    def run(self, value):
        return clean(value)
