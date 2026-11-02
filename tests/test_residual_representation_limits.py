"""Local configuration and optional diagnostics have no hidden size permission."""
from copy import deepcopy
import json

import pytest

import fetch_filing as ff
from ff_configuration import read_json_object
from ff_local_preparation_observation import local_preparation_observation, validated_local_preparation_observation
from filing_contracts import FilingFetchError
from test_local_preparation_observation import receipt


def test_explicit_local_configuration_is_read_complete(tmp_path):
    payload = {'schema': 'connection', 'explanation': '多根配置🙂' * 15000}
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    assert path.stat().st_size > 65536
    assert read_json_object(path) == payload
    path.write_bytes(b'\xff')
    with pytest.raises(FilingFetchError, match='invalid'):
        read_json_object(path)


def test_complete_optional_counters_can_exceed_old_shape_caps():
    payload = receipt()
    payload['diagnostics'] *= 1500
    branch = {'counter': 7}
    for _ in range(24):
        branch = {'next': branch}
    payload['operations'].extend([branch, {f'counter{i}': i for i in range(80)}])
    observed = local_preparation_observation(payload, {'max_candidates': 64, 'max_bytes': 134217728, 'timeout_seconds': 10})
    assert observed is not None and observed['diagnostics'] == payload['diagnostics']
    assert observed['operations'] == payload['operations']
    bad = deepcopy(observed)
    bad['operations'][0]['headers'] = {'authorization': 'unsafe'}
    assert validated_local_preparation_observation(bad) is None


@pytest.mark.parametrize('budget', [None, {'opaque_future_budget': 1}, {'path': 'not_public'}])
def test_bad_optional_budget_does_not_replace_primary_blocked_operation(budget):
    payload = {'operation_schema_version': '1.0', 'operation': 'ensure', 'status': 'blocked',
               'request_id': 'test-request', 'policy_hash': None,
               'local_preparation': {'status': 'blocked', 'reason': 'budget_exceeded',
                                     'blocks_download': True, 'causes': [], 'local_read_budget': budget}}
    original = deepcopy(payload)
    observed = ff._validated_operation(payload, 'ensure')
    assert observed['status'] == 'blocked'
    assert observed['local_preparation']['reason'] == 'budget_exceeded'
    assert 'local_read_budget' not in observed['local_preparation']
    assert payload == original


def test_padded_valid_supervisor_usage_does_not_become_unknown():
    from transcript_tool_transport import _provider_usage
    usage = {'schema_version': 'earnings-retrieval-usage/1', 'request_id': 'usage-test',
             'usage_complete': True, 'usage': {'requests_used': 3, 'response_bytes_used': 42}}
    raw = b' ' * 12000 + json.dumps(usage).encode()
    assert _provider_usage(raw, 'usage-test') == {'provider_requests': 3,
           'provider_response_bytes': 42, 'provider_usage_complete': True}
    assert _provider_usage(raw, 'other-request')['provider_usage_complete'] is False


@pytest.mark.parametrize('bad_usage', ['[' * 3000 + '0' + ']' * 3000, '9' * 5000], ids=['deep_json', 'huge_integer'])
def test_undecodable_optional_usage_is_unknown_not_a_main_failure(bad_usage):
    from transcript_tool_transport import _provider_usage
    raw = b' ' * 12000 + (
        '{"schema_version":"earnings-retrieval-usage/1","request_id":"bad-usage",'
        '"usage_complete":true,"usage":' + bad_usage + '}'
    ).encode()
    assert _provider_usage(raw, 'bad-usage') == {'provider_requests': None,
           'provider_response_bytes': None, 'provider_usage_complete': False}
