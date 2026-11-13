import pytest

from repo_tutor.config import Config, load_config


def test_environment_overrides_toml_without_printing_key(tmp_path, monkeypatch):
    path = tmp_path / 'config.toml'
    path.write_text('[repo_tutor]\nmodel="file-model"\nmax_calls=5\n')
    monkeypatch.setenv('REPO_TUTOR_MODEL', 'env-model')
    monkeypatch.setenv('REPO_TUTOR_API_KEY', 'unit-test-key')
    config = load_config(path)
    assert config.model == 'env-model' and config.max_calls == 5
    assert config.api_key == 'unit-test-key'
    assert 'unit-test-key' not in repr(config)


def test_unsafe_endpoint_and_invalid_limits():
    for endpoint in ('file:///etc/passwd', 'http://remote.example', 'https://user:pass@example.com'):
        with pytest.raises(ValueError):
            Config(base_url=endpoint)
    with pytest.raises(ValueError):
        Config(max_calls=0)


@pytest.mark.parametrize('kwargs', [{'nodes_per_lesson': '4'}, {'max_calls': True}, {'timeout': -1},
                                   {'api_key': 123}, {'model': ''}])
def test_configuration_type_errors_are_rejected(kwargs):
    with pytest.raises(ValueError):
        Config(**kwargs)
