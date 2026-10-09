# Findings

ET validator currently rejects HKEX as malformed before operation capability; capability has no exchange dimensions. FF forwards only existing environment, never the explicitly configured key file. CWP environment removes FMP_API_KEY but still inherits FMP_API_KEY_FILE.

Real loader/doctor initially rejected the proposed nonsecret credential-source field despite transport fixture success. Fixed both validation boundaries rather than relying on ad-hoc exports. ET/2 consumer initially rejected new typed capability/credential errors; the exact finite enum now matches actual producer outcomes. HTTP0 preflight and unknown usage remain distinct. Known-key raw/encoded contamination is rejected rather than rewriting source bytes. Source authentication/entitlement remains unverified until MAIN current M3 call.
