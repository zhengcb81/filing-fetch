# ROOT W07-FF-PERF reception — 2026-10-11

Accepted engineering scope: original 41 cases PASS, zero oracle findings, 99.9624 seconds,
original case/batch limits 30/180 seconds, two independent worker catalogs, 26 unique
verified proofs (15/12 per worker). Original request/response/case expectations and
14 non-seed handlers unchanged. Cutoff and measured-usage production fixes in
FF 2d380a05 and ET d0ac42c6 are exercised through actual offline FF→ET→CWP paths.
No real supplier reachability or economic truth is certified; no paid calls.

ROOT behavioral RED→GREEN: exclusively owned compact attempt caches; failed proof
cannot be overwritten by another worker; all worker proofs retained; child processes
reaped after repeated pipe failures; metric failures still restore scratch; seed
response cardinality/order/tag/request must match. Logical aliases are independent
catalog details; only actual byte/version/physical-original invariants must agree.
Initial ROOT overconstraint produced 28PASS/13PARTIAL at130.5777s and is preserved.
Final 225 focused regressions pass in4.92s. The two cheap W07 test files join the
existing shared push/CI runner; the complete41 remains a manual big-node test.

One old cache test required unsafe reuse; it now demands a distinct owned cache,
while retaining the original sentinel and restore assertions. No oracle reduction.

ROOT compressed two attempts and their request/response/fixture/usage bytes into
490060 bytes in company-wiki/.planning/w07-ff-perf-reception/offline-evidence.zip.
Run that directory's replay_evidence.py --ff-project <this checkout> to replay
unchanged oracle checks in a fresh temporary directory, then automatically clean it.
Canonical credentials/config and FF/ET WIP metadata remain unchanged.

Normal publication and narrow two-file skill installation are tracked in ROOT PWF;
this engineering receipt does not complete W04/G2/G4/G5.
