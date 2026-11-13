"""Explicit TOML/environment configuration; secrets never enter artifacts."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from urllib.parse import urlsplit

from repo_tutor.scanner import DEFAULT_EXCLUDES


@dataclass(frozen=True)
class Config:
    base_url: str = 'https://api.deepseek.com/v1'
    model: str = 'deepseek-chat'
    api_key: str = field(default='', repr=False)
    max_calls: int = 20
    max_output_tokens: int = 7000
    timeout: int = 180
    nodes_per_lesson: int = 24
    excerpt_lines: int = 45
    max_context_chars: int = 90000
    max_file_bytes: int = 1_000_000
    excludes: tuple[str, ...] = DEFAULT_EXCLUDES
    citation_proximity: int = 3

    def __post_init__(self):
        for name in ('base_url', 'model', 'api_key'):
            value = getattr(self, name)
            if not isinstance(value, str) or (name != 'api_key' and not value.strip()):
                raise ValueError(f'{name} must be a string; model and base_url cannot be empty')
        for name in ('max_calls', 'max_output_tokens', 'timeout', 'nodes_per_lesson',
                     'excerpt_lines', 'max_context_chars', 'max_file_bytes', 'citation_proximity'):
            value = getattr(self, name)
            if type(value) is not int or value < (0 if name == 'citation_proximity' else 1):
                raise ValueError(f'{name} must be a positive integer (proximity may be zero)')
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in ('https', 'http') or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError('base_url must be an HTTP(S) URL without credentials')
        if parsed.query or parsed.fragment:
            raise ValueError('base_url cannot contain query or fragment')
        if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('remote model endpoints require HTTPS')
        if not isinstance(self.excludes, (tuple, list)) or not all(isinstance(x, str) for x in self.excludes):
            raise ValueError('excludes must be a list of directory names')


def load_config(path: str | Path | None = None) -> Config:
    data = {}
    if path:
        data.update(tomllib.loads(Path(path).read_text()).get('repo_tutor', {}))
    known = {f.name: f for f in fields(Config)}
    if set(data) - set(known):
        raise ValueError('unknown configuration keys: ' + ', '.join(sorted(set(data) - set(known))))
    for name in known:
        value = os.getenv('REPO_TUTOR_' + name.upper())
        if value is not None:
            default = getattr(Config(), name)
            data[name] = int(value) if isinstance(default, int) else value.split(',') if name == 'excludes' else value
    data.setdefault('api_key', os.getenv('DEEPSEEK_API_KEY', os.getenv('OPENAI_API_KEY', '')))
    return Config(**data)
