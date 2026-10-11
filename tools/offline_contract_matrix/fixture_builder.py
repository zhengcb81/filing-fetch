"""Synthetic fixture originals and isolated scratch-environment builder.

This module is test-harness only. It never touches production configuration,
production originals, or any producer repository. Everything it writes lands in
an owned scratch root supplied by the caller.

The synthetic originals are *valid* small PDF / HTML / TXT files (a real PDF
with a correct cross-reference table, real HTML, real UTF-8 text), never a
``%PDF ...`` placeholder. Their metadata is explicitly marked synthetic.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SYNTHETIC_MARKER = "synthetic-w06-offline-contract-matrix"

# Fixed fake credential. This is NOT a real key and must never be confused with
# the user's config/FMP_API_KEY.txt (which this harness never reads).
FAKE_FMP_KEY = "offline-w06-not-a-real-fmp-key"

# Deterministic retrieval timestamp so double-run artifacts are byte-stable.
RETRIEVED_AT = "2026-01-01T00:00:00Z"


# ── valid synthetic originals ──────────────────────────────────────────────


def make_valid_pdf(text: str = "Synthetic offline fixture") -> bytes:
    """Return a small, structurally valid PDF (correct xref + trailer).

    This is a real, openable PDF — not a ``%PDF-`` magic placeholder. The xref
    byte offsets are computed from the actual object stream so the file passes a
    strict PDF parser's cross-reference check.
    """
    # A single page with a simple text-drawing content stream. The font is not
    # embedded (a standard-14 base font), which is valid PDF.
    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 120] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
    )
    # content stream
    content = f"BT /F1 12 Tf 24 60 Td ({text}) Tj ET".encode("latin-1", "replace")
    objects.append(
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n"
        + content + b"\nendstream"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref_offset = len(out)
    count = len(objects) + 1
    out += f"xref\n0 {count}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n"
        f"{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)


def make_valid_html(title: str, body: str) -> bytes:
    """Return a small, well-formed HTML document (UTF-8)."""
    html = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        f"<meta charset=\"utf-8\">\n<title>{title}</title>\n</head>\n<body>\n"
        f"<h1>{title}</h1>\n<p>{body}</p>\n"
        f"<p><em>{SYNTHETIC_MARKER}</em></p>\n"
        "</body>\n</html>\n"
    )
    return html.encode("utf-8")


def make_valid_txt(title: str, body: str) -> bytes:
    """Return a small UTF-8 plain-text original (e.g. an earnings-call TXT)."""
    text = f"{title}\n{'-' * len(title)}\n{body}\n\n[{SYNTHETIC_MARKER}]\n"
    return text.encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── identities used across the fixture (three markets + a call issuer) ────


@dataclass(frozen=True)
class Identity:
    market: str
    entity: str          # directory / canonical company name used by CWP
    canonical_name: str  # identity canonical name (matches security master)
    security_id: str
    ticker: str
    exchange: str
    provider: str
    source_url: str
    aliases: list[str]


CN = Identity(
    market="CN", entity="宁德时代", canonical_name="宁德时代", security_id="300750",
    ticker="300750", exchange="SZSE", provider="cninfo",
    source_url="https://www.cninfo.com.cn/new/disclosure/detail?stockCode=300750",
    aliases=["CATL"],
)
US = Identity(
    market="US", entity="Apple Inc.", canonical_name="Apple Inc.", security_id="AAPL",
    ticker="AAPL", exchange="NASDAQ", provider="sec",
    source_url="https://www.sec.gov/Archives/edgar/data/0000320193/syn-10k.htm",
    aliases=["AAPL", "APPLE"],
)
HK = Identity(
    market="HK", entity="騰訊控股", canonical_name="騰訊控股", security_id="00700",
    ticker="00700", exchange="HKEX", provider="hkexnews",
    source_url="https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0408/syn.pdf",
    aliases=["TENCENT", "腾讯", "腾讯控股", "騰訊"],
)

IDENTITIES = {"CN": CN, "US": US, "HK": HK}


def synthetic_security_master(market: str) -> dict[str, Any]:
    """Deterministic minimal ``security_master`` record for offline identify."""
    ident = IDENTITIES[market.upper()]
    record = {
        "active": True,
        "aliases": list(ident.aliases),
        "canonical_name": ident.canonical_name,
        "exchange": ident.exchange,
        "identifiers": {"org_id": f"syn-{market.lower()}-0001"},
        "market": ident.market,
        "schema_version": "1.0",
        "security_id": ident.security_id,
        "source_name": ident.provider,
        "source_record_id": f"syn-{market.lower()}-0001",
        "source_url": ident.source_url,
        "ticker": ident.ticker,
    }
    return {
        "schema_version": "1.0",
        "market": ident.market,
        "retrieved_at": "2000-01-01T00:00:00Z",
        "sources": [ident.source_url],
        "record_count": 1,
        "records": [record],
    }


# ── configuration templates ────────────────────────────────────────────────

_CATALOG_YAML = """schema_version: "1.0"
catalog_dir: "${PROJECT_ROOT}/.source_catalog"
roots:
  - root_id: company_raw
    kind: company_raw
    path: "${PROJECT_ROOT}/companies"
    priority: 10
  - root_id: local_company
    kind: directory
    path: "${PROJECT_ROOT}/positions/local_company"
    priority: 20
  - root_id: external_dayu
    kind: directory
    path: "${PROJECT_ROOT}/positions/external_dayu"
    priority: 30
  - root_id: external_dropbox
    kind: directory
    path: "${PROJECT_ROOT}/positions/external_dropbox"
    priority: 40
"""

_WORKER_YAML = """schema_version: "1.0"
"""


def _acquisition_yaml(adapter_script: Path) -> str:
    """source_acquisition.yaml pointing cn/hk/us at the owned fixture adapter.

    cn uses json_command_v1; hk/us use dayu_sdk_bounded_v1 (the only way the
    config loader routes HK/US through the JSON-command adapter) — all three
    call the same owned fixture-provider script. bounded adapters must declare
    supports_acquisition_budget and echo a valid acquisition_usage.
    """
    command = json.dumps([sys.executable, str(adapter_script)])
    return (
        'schema_version: "1.1"\n'
        'staging_root: "${PROJECT_ROOT}/.source_catalog/staging"\n'
        "timeout_seconds: 60\n"
        "adapters:\n"
        "  cn:\n"
        '    name: "w06-fixture-cn"\n'
        '    version: "1.0.0"\n'
        '    interface: "json_command_v1"\n'
        "    supports_acquisition_budget: true\n"
        '    project_root: "${PROJECT_ROOT}"\n'
        "    config_root: null\n"
        f"    command: {command}\n"
        "  hk:\n"
        '    name: "w06-fixture-hk"\n'
        '    version: "1.0.0"\n'
        '    interface: "dayu_sdk_bounded_v1"\n'
        "    supports_acquisition_budget: true\n"
        '    project_root: "${PROJECT_ROOT}"\n'
        "    config_root: null\n"
        f"    command: {command}\n"
        "  us:\n"
        '    name: "w06-fixture-us"\n'
        '    version: "1.0.0"\n'
        '    interface: "dayu_sdk_bounded_v1"\n'
        "    supports_acquisition_budget: true\n"
        '    project_root: "${PROJECT_ROOT}"\n'
        "    config_root: null\n"
        f"    command: {command}\n"
    )


# document_kind -> storage subdir (mirrors CWP canonical_writer mapping)
KIND_SUBDIR = {
    "annual_report": "financial_reports/annual",
    "semi_annual_report": "financial_reports/semi_annual",
    "quarterly_report": "financial_reports/quarterly",
    "prospectus": "prospectus",
    "equity_offering_prospectus": "prospectus",
    "convertible_bond_prospectus": "prospectus",
    "investor_relations": "investor_relations",
    "investor_call_transcript": "investor_relations/transcripts",
}


class ScratchEnvironment:
    """Owns a fully isolated scratch root for one runner attempt.

    Layout::

        <scratch>/
          ff/company_wiki.json        FF launcher config (company_wiki_root=<wiki>)
          wiki/                       CWP wiki root == company_wiki_root
            config/{source_catalog,source_acquisition,source_catalog_worker}.yaml
            .source_catalog/{security_master,staging}
            companies/<entity>/raw/...
            positions/{local_company,external_dayu,external_dropbox}
          proxy/                      ET test-proxy state (calls, tmp, fixtures)
          fake_fmp_key.txt            fixed fake credential file
    """

    def __init__(self, scratch: Path, *, adapter_script: Path, et_proxy: Path) -> None:
        self.scratch = scratch
        self.wiki = scratch / "wiki"
        self.ff_config = scratch / "ff" / "company_wiki.json"
        self.proxy_state = scratch / "proxy"
        self.fake_key = scratch / "fake_fmp_key.txt"
        self.adapter_script = adapter_script
        self.et_proxy = et_proxy
        self._build()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        for sub in (
            self.wiki / "config",
            self.wiki / ".source_catalog" / "security_master",
            self.wiki / "companies",
            self.wiki / "positions" / "local_company",
            self.wiki / "positions" / "external_dayu",
            self.wiki / "positions" / "external_dropbox",
            self.proxy_state / "calls",
            self.proxy_state / "tmp",
            self.proxy_state / "fixtures",
            self.scratch / "ff",
        ):
            sub.mkdir(parents=True, exist_ok=True)

        config = self.wiki / "config"
        (config / "source_catalog.yaml").write_text(_CATALOG_YAML, encoding="utf-8")
        (config / "source_catalog_worker.yaml").write_text(_WORKER_YAML, encoding="utf-8")
        (config / "source_acquisition.yaml").write_text(
            _acquisition_yaml(self.adapter_script), encoding="utf-8"
        )

        master = self.wiki / ".source_catalog" / "security_master"
        for market in ("cn", "hk", "us"):
            (master / f"{market}.json").write_text(
                json.dumps(synthetic_security_master(market.upper()), ensure_ascii=False),
                encoding="utf-8",
            )

        self.fake_key.write_text(FAKE_FMP_KEY, encoding="utf-8")

        self.ff_config.parent.mkdir(parents=True, exist_ok=True)
        self.ff_config.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "company_wiki_root": str(self.wiki),
                    "earnings_transcripts_tool": str(self.et_proxy),
                    "fmp_api_key_file": str(self.fake_key),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    # -- helpers -----------------------------------------------------------

    def seed_original(
        self,
        identity: Identity,
        *,
        document_kind: str,
        fiscal_year: int,
        fiscal_period: str | None,
        form_type: str | None,
        published_date: str,
        content: bytes,
        mime_type: str,
        filename_hint: str,
    ) -> Path:
        """Write a seeded original + sidecar into the company_raw root."""
        ext = {"application/pdf": ".pdf", "text/html": ".html", "text/plain": ".txt"}[mime_type]
        sub = KIND_SUBDIR.get(document_kind, "other")
        directory = self.wiki / "companies" / identity.entity / "raw" / sub
        directory.mkdir(parents=True, exist_ok=True)
        filename = f"{filename_hint}{ext}"
        target = directory / filename
        target.write_bytes(content)
        sidecar = {
            "market": identity.market,
            "security_id": identity.security_id,
            "source_title": f"{identity.canonical_name} {document_kind} {fiscal_year}",
            "provider": identity.provider,
            "provider_document_id": f"syn-{identity.market.lower()}-{fiscal_year}",
            "source_url": identity.source_url,
            "published_date": published_date,
            "fiscal_year": fiscal_year,
            "document_kind": document_kind,
            "synthetic": True,
        }
        if form_type is not None:
            sidecar["form_type"] = form_type
        if fiscal_period is not None:
            sidecar["fiscal_period"] = fiscal_period
        (directory / (filename + ".source.json")).write_text(
            json.dumps(sidecar, ensure_ascii=False), encoding="utf-8"
        )
        return target

    def calls_file(self, case_id: str) -> Path:
        return self.proxy_state / "calls" / f"{case_id}.jsonl"

    def et_temp_root(self) -> Path:
        return self.proxy_state / "tmp"

    def proxy_env(self) -> dict[str, str]:
        """Minimal synthetic environment for FF/ET child processes."""
        env = {
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "FMP_API_KEY": FAKE_FMP_KEY,
            "W06_MATRIX_SCRATCH": str(self.scratch),
            "W06_MATRIX_STATE": str(self.proxy_state / "state.json"),
        }
        return env
