"""Caller resource allocation reaches ET without a second hidden cap."""
import json

import pytest

import transcript_tool_transport as module


@pytest.mark.parametrize('timeout,remaining,expected',[(120,180,120),(120,100,97),(10,30,10)])
def test_explicit_resources_reach_the_et_owner(tmp_path,monkeypatch,timeout,remaining,expected):
    tool=tmp_path/'offline_tool.py'
    tool.write_text('# public subprocess boundary injected before any key/network',encoding='utf-8')
    transport=module.EarningsTranscriptsTransport(wiki_root=tmp_path,transcript_tool=tool,deadline=1)
    monkeypatch.setattr(transport,'_remaining',lambda:remaining)
    monkeypatch.setattr(transport,'_et_environment',lambda:({},None))
    seen=[]
    def run(command,*,input_bytes,timeout_seconds,**kwargs):
        seen.append((json.loads(input_bytes),timeout_seconds))
        usage={'schema_version':'earnings-retrieval-usage/1','request_id':'owner-budget',
               'usage_complete':True,'usage':{'requests_used':1,'response_bytes_used':321}}
        return json.dumps({'status':'content_too_large','error_code':'byte_limit'}).encode(),json.dumps(usage).encode(),2
    monkeypatch.setattr(module,'_run_bounded_json',run)
    limit=20*1024*1024
    result=transport._et_result(request={'request_id':'owner-budget','security_id':'EXAMPLE','exchange':'NASDAQ',
        'fiscal_year':2026,'fiscal_quarter':2,'as_of_date':'2026-10-09'},
        limits={'timeout_seconds':timeout,'max_bytes':limit,'max_cost_usd':'0.00'})
    assert len(seen)==1
    request,outer_timeout=seen[0]
    assert (request['max_body_bytes'],request['max_response_bytes'],request['timeout_seconds'])==(limit,limit,expected)
    assert outer_timeout==min(expected+3,remaining)
    assert result['reason']=='byte_limit' and result['provider_requests']==1
    assert result['provider_response_bytes']==321 and result['provider_usage_complete'] is True


def test_actual_parent_deadline_stops_before_a_provider_child(tmp_path,monkeypatch):
    tool=tmp_path/'offline_tool.py'
    tool.write_text('# never launched',encoding='utf-8')
    transport=module.EarningsTranscriptsTransport(wiki_root=tmp_path,transcript_tool=tool,deadline=1)
    monkeypatch.setattr(transport,'_remaining',lambda:3.75)
    def forbidden(*a,**k):raise AssertionError('true remaining budget must stop before launch/key access')
    monkeypatch.setattr(transport,'_et_environment',forbidden)
    monkeypatch.setattr(module,'_run_bounded_json',forbidden)
    result=transport._et_result(request={},limits={'timeout_seconds':120,'max_bytes':20*1024*1024,'max_cost_usd':'0.00'})
    assert result['reason']=='provider_deadline' and result['provider_calls']==0


def test_et_encoded_response_uses_the_operation_allocation(tmp_path,monkeypatch):
    tool=tmp_path/'offline_tool.py'
    tool.write_text('# no provider execution',encoding='utf-8')
    transport=module.EarningsTranscriptsTransport(wiki_root=tmp_path,transcript_tool=tool,deadline=1)
    monkeypatch.setattr(transport,'_remaining',lambda:180)
    monkeypatch.setattr(transport,'_et_environment',lambda:({},None))
    seen=[]
    def run(command,*,input_bytes,**kwargs):
        seen.append(kwargs)
        return b'{"schema_version":"earnings-transcript-result/2","request_id":"wire-cap","status":"not_found","provider":"fmp","fiscal_period":"2026-Q2","candidate_count":0}',b'',0
    monkeypatch.setattr(module,'_run_bounded_json',run)
    raw=128*1024*1024
    result=transport._et_result(request={'request_id':'wire-cap','security_id':'EXAMPLE','exchange':'NASDAQ',
        'fiscal_year':2026,'fiscal_quarter':2,'as_of_date':'2026-10-09'},
        limits={'timeout_seconds':120,'max_bytes':raw,'max_cost_usd':'0.00'})
    assert len(seen)==1
    # The real bounded transport already enforces this allocation while reading.
    # A default32MiB bound cannot hold a valid128MiB source's base64 result.
    cap=seen[0].get('stdout_cap_bytes',module.MAX_JSON_OUTPUT_BYTES)
    assert type(cap) is int and cap>raw*4/3
    assert cap<=raw*32+2*1024*1024
    assert result['status']=='not_found'


def test_verified_source_open_allocates_exact_bytes_and_full_receipt(tmp_path,monkeypatch):
    import hashlib
    import sys
    import ff_process_transport as process
    raw=b'abc'
    digest=hashlib.sha256(raw).hexdigest()
    ref={'document_id':'owner-source','source_id':'urn:company-wiki:source:sha256:'+digest,
         'content_sha256':digest,'byte_size':len(raw)}
    receipt={'status':'ok',**ref,'manifest':{'title':'x'*90000}}
    script=('import sys,json\nr='+repr({**receipt,'manifest':{'title':''}})+"\nr['manifest']['title']='x'*90000\nsys.stdout.buffer.write("+repr(raw)+')\nsys.stderr.write(json.dumps(r))')
    transport=module.EarningsTranscriptsTransport(wiki_root=tmp_path,deadline=1)
    monkeypatch.setattr(transport,'_remaining',lambda:10)
    monkeypatch.setattr(transport,'_wiki_env',lambda:None)
    seen=[]
    def local_source(command,**kwargs):
        seen.append(kwargs)
        return process.run_bounded_json([sys.executable,'-B','-c',script],**kwargs)
    monkeypatch.setattr(module,'_run_bounded_json',local_source)
    result=transport._verified_open(ref)
    assert result['manifest']==receipt['manifest']
    assert seen[0]['stdout_cap_bytes']==len(raw)
    assert seen[0]['stderr_cap_bytes'] is None


@pytest.mark.parametrize('channel',['stdout','stderr'])
def test_explicit_process_channel_quota_still_bounds_real_read(channel):
    import sys
    import ff_process_transport as process
    command=[sys.executable,'-B','-c',"import sys;sys."+channel+".write('x'*1025)"]
    kwargs={'stdout_cap_bytes':1024,'stderr_cap_bytes':None}
    if channel=='stderr':
        kwargs['stderr_cap_bytes']=1024
        # Diagnostics: the explicit quota bounds retained bytes, not the result.
        stdout,stderr,code=process.run_bounded_json(command,timeout_seconds=10,**kwargs)
        assert code==0
        assert stdout==b''
        assert len(stderr)<=1024
        return
    with pytest.raises(process.OutputLimitExceeded):
        process.run_bounded_json(command,timeout_seconds=10,**kwargs)
