"""Local I/O observations survive real bounded child and FF CLI failures."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

import fetch_filing as ff
import ff_local_source_prepare as local
import ff_process_transport as transport
from filing_contracts import FilingFetchError
from test_r1_source_business_failure import child
from test_source_ref_v2_db_query import DOCUMENT, _identity, _query, _wiki


def receipt():
    return {
        'schema_version': 'local-source-prepare/1', 'status': 'unavailable',
        'reason': 'budget_exceeded', 'source_ref': None, 'blocks_download': True,
        'operations': [{'status': 'recorded', 'assertion_id': 'assertion-fixture', 'restore_audit_id': None}],
        'diagnostics': [{'document_id': DOCUMENT, 'reason': 'local_original_missing', 'status': 'unavailable'}],
        'download_events': 0,
    }


@pytest.mark.parametrize('exit_code', [0, 1])
def test_real_child_preserves_local_receipt_and_actual_distinct_request_limits(tmp_path, exit_code):
    payload = receipt()
    captured = []

    def actual(command, **kwargs):
        captured.append(json.loads(kwargs['input_bytes']))
        return transport.run_bounded_json(child(payload, exit_code), **kwargs)

    with pytest.raises(FilingFetchError) as caught:
        local.prepare_existing_local_source(root=tmp_path, source_request={'entity': 'Fixture'},
            deadline=time.monotonic()+20, stats={'calls': 0, 'downloads': 0},
            transport=actual, physical_fields=ff._contains_physical_field)
    error = caught.value
    assert error.producer_exit_code == exit_code
    assert error.upstream_cause['code'] == 'budget_exceeded'
    observation = error.local_preparation_observation
    assert observation['schema_version'] == 'filing-local-preparation-observation/1'
    assert observation['usage_scope'] == 'local_original_verification'
    assert observation['reason'] == payload['reason']
    assert observation['operations'] == payload['operations']
    assert observation['diagnostics'] == payload['diagnostics']
    assert observation['local_read_limits'] == captured[0]['limits']
    assert observation['local_read_limits']['max_bytes'] == 128*1024*1024
    assert observation['local_io_usage'] is None
    snapshot = deepcopy(observation)
    payload['operations'].clear()
    assert observation == snapshot


@pytest.mark.parametrize('large', [False, True])
def test_real_ff_cli_preserves_bounded_local_failure_without_retry_or_provider(tmp_path, large):
    root = _wiki(tmp_path)
    config = tmp_path/'connection.json'
    config.write_text(json.dumps({'schema_version': '1.0', 'company_wiki_root': str(root)}), encoding='utf-8')
    request = {'schema_version': '2.0', 'company_query': 'AMD', 'market': 'US',
        'document_kind': 'semi_annual_report', 'mode': 'exact', 'fiscal_year': 2026,
        'fiscal_period': 'H1', 'as_of_date': '2026-10-21', 'filing_intent': 'reuse_only'}
    target = tmp_path/'request.json'
    target.write_text(json.dumps(request), encoding='utf-8')
    local_payload = receipt()
    if large:
        local_payload['diagnostics'] = [{'document_id': 'urn:company-wiki:document:sha256:'+format(i, '064x'),
            'reason': 'registered_identity_conflict', 'status': 'unavailable'} for i in range(600)]
    payload_file = tmp_path/'producers.json'
    payload_file.write_text(json.dumps({'identity': _identity(), 'query': _query('not_found'), 'local': local_payload}), encoding='utf-8')
    launcher = tmp_path/'fixture_cli.py'
    launcher.write_text('''import json,sys
sys.path.insert(0,sys.argv.pop(1))
import fetch_filing as ff
import ff_process_transport as transport
payload_file=sys.argv.pop(1)
real=transport.run_bounded_json
seen=[]
def routed(command,**kwargs):
    name='local' if 'company_wiki.source_catalog.local_prepare_cli' in command else ('query' if 'company_wiki.source_catalog.source_query_cli' in command else ('identity' if 'identify' in command else None))
    if name is None: raise AssertionError('unexpected producer route')
    seen.append(name)
    code="import json,sys; print(json.dumps(json.load(open(sys.argv[1],encoding='utf-8'))[sys.argv[2]]))"
    return real([sys.executable,'-S','-c',code,payload_file,name],**kwargs)
ff._run_bounded_json=routed
raise SystemExit(ff.main(sys.argv[1:]))
''',encoding='utf-8')
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(launcher),
        str(Path(ff.__file__).parent), str(payload_file),
        '--request-file', str(target), '--config', str(config), '--source-ref-v2', '--timeout-seconds', '20'],
        capture_output=True, timeout=30, check=False)
    assert result.returncode == 2, result.stderr.decode()
    output = json.loads(result.stdout)
    assert output['filing']['upstream_cause']['code'] == 'budget_exceeded', output
    assert output['calls'] == 3 and output['downloads'] == 0
    assert output['local_preparation_observation']['diagnostics'] == local_payload['diagnostics']
    if large:
        assert len(result.stdout) > 65536
    assert output['local_preparation_observation']['local_io_usage'] is None


@pytest.mark.parametrize('change', [
    {'diagnostics': [{'path': 'unwanted/file.pdf'}]},
    {'diagnostics': [{'reason': 'Bearer token is not a machine code'}]},
    {'operations': [{'headers': {'Authorization': 'secret'}}]},
    {'diagnostics': ['not_an_operation']},
    {'operations': [{'status': 'unchanged'}]*1025},
    {'local_io_usage': {'bytes_read': 0}},
    {'local_read_limits': {'max_candidates': True, 'max_bytes': 1, 'timeout_seconds': 1}},
    {'local_read_limits': {'max_candidates': 64, 'max_bytes': 134217728, 'timeout_seconds': float('nan')}},
    {'unexpected': 'hidden'},
    {'reason': {'unexpected': 'not_a_reason_code'}},
    {'local_read_limits': {'max_candidates': 64, 'max_bytes': 134217728, 'timeout_seconds': 2**2048}},
])
def test_optional_observation_rejects_unsafe_or_wrong_type_without_replacing_safe_cause(change):
    from ff_local_preparation_observation import local_preparation_observation, validated_local_preparation_observation
    from ff_v2_envelope import error_envelope
    from ff_provider_cause import source_condition
    limits = {'max_candidates': 64, 'max_bytes': 128*1024*1024, 'timeout_seconds': 10}
    valid = local_preparation_observation(receipt(), limits)
    invalid = {**valid, **change}
    assert validated_local_preparation_observation(invalid) is None
    cause = source_condition('local_prepare', 'budget_exceeded')
    output = error_envelope('upstream_error', 'budget_exceeded', retryable=True,
        upstream_cause=cause, local_preparation_observation=invalid)
    assert output['filing']['upstream_cause'] == cause
    assert 'local_preparation_observation' not in output


def test_unknown_owner_machine_diagnostic_is_preserved_without_new_business_enum():
    from ff_local_preparation_observation import local_preparation_observation
    payload = receipt()
    payload['reason'] = 'future_owner_bound'
    payload['operations'].append({'schema_version': 'future-owner-observation/1',
        'phase': 'original_verify', 'consumed': {'bytes_read': 7, 'complete': False}})
    observed = local_preparation_observation(payload,
        {'max_candidates': 64, 'max_bytes': 128*1024*1024, 'timeout_seconds': 10})
    assert observed['reason'] == payload['reason']
    assert observed['operations'] == payload['operations']
    assert observed['local_io_usage'] is None


def test_native_local_budget_operation_is_verbatim_and_is_not_provider_usage():
    from ff_local_preparation_observation import local_preparation_observation
    from ff_v2_envelope import error_envelope
    from ff_provider_cause import source_condition
    operation = {'schema_version': 'local-read-budget/1', 'operation': 'local_read_budget',
        'usage_scope': 'local_original_verification', 'phase': 'original_read',
        'reason': 'budget_exceeded',
        'limits': {'max_candidates': 64, 'max_bytes': 134217728, 'timeout_seconds': 18.5,
            'max_discovery_groups': 256, 'max_discovery_entries': 4096},
        'consumed': {'candidates': 5, 'charged_read_bytes': 134217720,
            'observed_charge_bytes': 134217729, 'discovery_groups': 9,
            'discovery_entries': 42, 'elapsed_seconds': 0.125},
        'triggered_bound': 'max_bytes'}
    payload = receipt()
    payload['operations'].append(operation)
    limits = {'max_candidates': 64, 'max_bytes': 134217728, 'timeout_seconds': 18.5}
    observed = local_preparation_observation(payload, limits)
    assert observed['operations'][-1] == operation
    assert observed['local_io_usage'] is None
    cause = source_condition('local_prepare', 'budget_exceeded')
    assert cause['provider_started'] is False and cause['usage_complete'] is True
    output = error_envelope('upstream_error', 'budget_exceeded', retryable=True,
        upstream_cause=cause, local_preparation_observation=observed)
    assert output['local_preparation_observation'] == observed
    assert output['local_preparation_observation']['operations'][-1]['consumed']['observed_charge_bytes'] > operation['consumed']['charged_read_bytes']
    assert 'acquisition_observation' not in output
    operation['triggered_bound'] = None
    assert local_preparation_observation(payload, limits)['operations'][-1]['triggered_bound'] is None


@pytest.mark.parametrize('schema', [
    'C:/Users/example/raw.pdf', 'file:///C:/Users/example/raw.pdf',
    'D:/1', 'https://example.com/1', 'FILE:///tmp/raw.pdf',
    'file:/C:/Users/example/raw.pdf', 'FiLe:/tmp/raw.pdf', 'file:/1',
])
def test_nested_schema_is_a_machine_identifier_not_a_physical_address(schema):
    from ff_local_preparation_observation import local_preparation_observation
    from ff_v2_envelope import error_envelope
    from ff_provider_cause import source_condition
    payload = receipt()
    payload['operations'].append({'schema_version': schema})
    observed = local_preparation_observation(payload,
        {'max_candidates': 64, 'max_bytes': 134217728, 'timeout_seconds': 10})
    assert observed is None
    cause = source_condition('local_prepare', 'budget_exceeded')
    output = error_envelope('upstream_error', 'budget_exceeded', retryable=True,
        upstream_cause=cause, local_preparation_observation=observed)
    assert output['filing']['upstream_cause'] == cause
    assert 'local_preparation_observation' not in output


@pytest.mark.parametrize('schema', ['future-owner/2.1', 'local-read-budget/1',
    'future-owner', 'urn:owner:v2', 'owner+namespace/3-beta', 'urn:owner:budget/2',
    'owner/schema/1'])
def test_unknown_schema_machine_identifiers_remain_verbatim(schema):
    from ff_local_preparation_observation import local_preparation_observation
    payload = receipt()
    payload['operations'].append({'schema_version': schema, 'future_counter': 7,
        'reason': 'file:missing'})
    observed = local_preparation_observation(payload,
        {'max_candidates': 64, 'max_bytes': 134217728, 'timeout_seconds': 10})
    assert observed['operations'] == payload['operations']
