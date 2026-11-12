# public_operation_isolation fixtures

These files are **test stand-ins for public contracts**, not implementations of
company-wiki or earnings-transcripts.

- `independent_service.py` accepts one configured operation name as its first
  argument and answers the public wire shapes FF consumes. It records every
  invocation (argv, cwd, inherited `PYTHONPATH`, stdin) in `MBFF_CALL_LOG`.
- `transcript_tool.py` is a plain `.py` ET stand-in selected through the legacy
  `earnings_transcripts_tool` deployment field. It emits the public
  `earnings-transcript-result/2` and `earnings-retrieval-usage/1` wires.

They deliberately contain no provider, storage, database or sibling-checkout
logic. Tests launch the real FF CLI from an empty working directory with an
explicit connection config; the fixtures only make the launched commands
observable.
