"""
RFP Dashboard — Flask web UI.
Entry point: run_dashboard.py  →  http://localhost:5000
"""

import csv
import io
import os
import re
import subprocess
import zipfile
from pathlib import Path
from datetime import date

from flask import Flask, render_template_string, jsonify, request

from core.utils import ROOT_DIR, DATA_DIR, DOWNLOADS_DIR, LOGS_DIR

CSV_FILE = ROOT_DIR / "data" / "rfp_tracker.csv"
LOG_FILE  = LOGS_DIR / "rfp_agent.log"

app = Flask(__name__)


# ── CSV helpers ───────────────────────────────────────────────────────────────

def load_rfps() -> list:
    if not CSV_FILE.exists():
        return []
    with open(CSV_FILE, encoding="utf-8-sig") as f:
        return list(reversed(list(csv.DictReader(f))))


def get_stats(rows: list) -> dict:
    today   = date.today().strftime("%Y-%m-%d")
    sources = sorted({r.get("source", "") for r in rows if r.get("source")})
    return {
        "total":       len(rows),
        "today":       sum(1 for r in rows if r.get("date", "").startswith(today)),
        "downloaded":  sum(1 for r in rows if r.get("file", "").strip()),
        "sources":     len(sources),
        "source_list": sources,
    }


def get_last_run() -> str:
    if not LOG_FILE.exists():
        return "Never"
    for line in reversed(LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()):
        if "RFP Agent" in line:
            return line[:19]
    return "—"


# ── PDF text extractor ────────────────────────────────────────────────────────

def _pdf_text(pdf_bytes: bytes, max_pages: int = 12) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            parts = []
            for page in pdf.pages[:max_pages]:
                t = page.extract_text() or ""
                parts.append(t)
            return "\n".join(parts)
    except Exception:
        return ""


def _is_toc_line(line: str) -> bool:
    """Table-of-contents lines end with dots then a page number: 'Title .... 14'"""
    return bool(re.search(r'\.{4,}\s*\d+\s*$', line.strip()))


def _split_paragraphs(text: str) -> list:
    """Split text into non-empty paragraphs (blank-line separated), skipping TOC lines."""
    paras, buf = [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if buf:
                paras.append(" ".join(buf))
            buf = []
        elif not _is_toc_line(line):
            buf.append(line)
    if buf:
        paras.append(" ".join(buf))
    return [p for p in paras if len(p) > 20]


def extract_rfp_info(file_path: str) -> dict:
    """Read a PDF or ZIP and return a dict of key RFP fields."""
    path = Path(file_path)
    text = ""

    try:
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as z:
                # prefer RFE/RFP/main doc over financial bid
                candidates = sorted(
                    [f for f in z.namelist() if f.lower().endswith(".pdf")],
                    key=lambda n: (
                        any(x in n.lower() for x in ("dfb", "financial", "boq")),
                        n,
                    ),
                )
                for name in candidates[:3]:
                    with z.open(name) as pf:
                        text += _pdf_text(pf.read()) + "\n"
                        if len(text) > 8000:
                            break
        elif path.suffix.lower() == ".pdf":
            text = _pdf_text(path.read_bytes(), max_pages=15)
    except Exception as e:
        return {"error": str(e), "raw_text": ""}

    info: dict = {"raw_text": text[:6000]}

    # Clean text: remove TOC lines for most searches
    clean_lines = [l for l in text.splitlines() if not _is_toc_line(l)]
    clean = "\n".join(clean_lines)
    paras = _split_paragraphs(text)   # list of paragraph strings

    def _find(patterns, src=None):
        src = src or clean
        for pat in patterns:
            m = re.search(pat, src, re.IGNORECASE)
            if m:
                return m.group(1).strip()[:120]
        return ""

    # ── Document type ──────────────────────────────────────────────────────────
    if re.search(r"Request for Empanelment|RFE No\.", text, re.IGNORECASE):
        info["doc_type"] = "Request for Empanelment (RFE)"
    elif re.search(r"Request for Proposal|RFP No\.", text, re.IGNORECASE):
        info["doc_type"] = "Request for Proposal (RFP)"
    elif re.search(r"Request for Quotation|RFQ", text, re.IGNORECASE):
        info["doc_type"] = "Request for Quotation (RFQ)"
    elif re.search(r"Bid Document|GeM/\d{4}/B/", text, re.IGNORECASE):
        info["doc_type"] = "GeM Bid Document"
    else:
        info["doc_type"] = "Tender Document"

    # ── Structured fields (use clean text to skip TOC lines) ──────────────────
    info["ref_number"] = _find([
        r"RFE No\.\s*[:\-]?\s*([^\n\r]{5,60})",
        r"RFP No\.\s*[:\-]?\s*([^\n\r]{5,60})",
        r"Bid Number\s*[:\-]?\s*([^\n\r]{5,40})",
        r"Tender No\.\s*[:\-]?\s*([^\n\r]{5,60})",
        r"(GEM/\d{4}/B/\d+)",
    ])

    info["organization"] = _find([
        r"Name of Organiz[a-z]+\s*[:\-]?\s*([^\n\r]{5,80})",
        r"Organisation Name\s*[:\-]?\s*([^\n\r]{5,80})",
        r"Procuring\s+Entity\s*[:\-]?\s*([^\n\r]{5,80})",
        r"Ministry\s*/\s*State Name\s*[:\-]?\s*([^\n\r]{5,80})",
    ])

    info["ministry"] = _find([
        r"Ministry of\s+([^\n\r]{5,80})",
        r"Department of\s+([^\n\r]{5,80})",
    ])

    info["category"] = _find([
        r"Service Category\s*[:\-]?\s*([^\n\r]{5,100})",
        r"Item Category\s*[:\-]?\s*([^\n\r]{5,100})",
        r"Empanelment Categories?\s*[:\-]?\s*([^\n\r]{5,100})",
    ])

    info["deadline"] = _find([
        r"Last Date.*?(?:Submission|Bid)\s*[:\-]?\s*([^\n\r]{5,60})",
        r"Bid End Date\s*/\s*Time\s*[:\-]?\s*([^\n\r]{5,60})",
        r"Closing Date\s*[:\-]?\s*([^\n\r]{5,60})",
        r"Deadline\s*[:\-]?\s*([^\n\r]{5,60})",
    ])

    info["contract_period"] = _find([
        r"Contract.*?Period\s*[:\-]?\s*([^\n\r]{5,80})",
        r"Empanelment.*?Period\s*[:\-]?\s*([^\n\r]{5,80})",
        r"Duration\s*[:\-]?\s*([^\n\r]{5,80})",
    ])

    info["emd"] = _find([
        r"Earnest Money Deposit.*?(?:INR|Rs\.?)\s*([\d,]+)",
        r"EMD.*?(?:INR|Rs\.?)\s*([\d,]+)",
    ])
    if info["emd"]:
        info["emd"] = "INR " + info["emd"]

    info["vendor_panel_size"] = _find([
        r"Vendor Panel Size\s*[:\-]?\s*([^\n\r]{5,80})",
        r"Number of Vendors?\s*[:\-]?\s*([^\n\r]{5,80})",
    ])

    info["contact"] = _find([
        r"([\w.+-]+@(?:nic\.in|nicsi\.nic\.in|gov\.in|[\w.-]+\.in))",
        r"Email\s*[:\-]?\s*([\w.@+-]+)",
    ])

    # ── Startup / MSE eligibility ──────────────────────────────────────────────
    # Collect paragraphs that mention startup/MSE — TOC lines already excluded
    _SUP = re.compile(r'\b(startup|MSE|MSME|DPIIT)\b', re.IGNORECASE)
    startup_paras = [p for p in paras if _SUP.search(p)]

    if startup_paras:
        info["startup_eligible"] = True
        # Pick up to 3 most informative paragraphs (longer = more context)
        top = sorted(startup_paras, key=len, reverse=True)[:3]
        # Trim each to ~180 chars so the notes stay readable
        info["startup_notes"] = " | ".join(p[:180] for p in top)
    else:
        info["startup_eligible"] = False
        info["startup_notes"] = ""

    # ── Scope of Work ─────────────────────────────────────────────────────────
    # Find the actual section body, not the TOC entry.
    # Strategy: locate the "SCOPE OF WORK" heading in clean text, then grab
    # the first substantive paragraph that follows it (skip sub-headings).
    scope_summary = ""
    scope_m = re.search(
        r'(?:^|\n)\s*(?:\d+[\.\d]*\s+)?SCOPE OF WORK\s*\n([\s\S]{1,2000})',
        clean, re.IGNORECASE
    )
    if scope_m:
        body = scope_m.group(1)
        # Walk paragraphs inside the section; take first one with >= 60 chars
        for line in body.splitlines():
            line = line.strip()
            # Stop if we hit the next numbered section heading
            if re.match(r'^\d+[\.\d]*\s+[A-Z]', line) and len(line) < 60:
                break
            if len(line) >= 60:
                scope_summary = line[:350]
                break

    # Fallback: first paragraph in the document that mentions the objective
    if not scope_summary:
        for p in paras:
            if re.search(r'\b(objective|empanel|procure|provide|deploy|manage)\b', p, re.IGNORECASE):
                if len(p) >= 80:
                    scope_summary = p[:350]
                    break

    info["scope_summary"] = scope_summary

    return info


# ── HTML template ─────────────────────────────────────────────────────────────

TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RFP Dashboard</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
<style>
  body { background:#f0f2f5; font-family:'Segoe UI',sans-serif; }
  .navbar { background:linear-gradient(135deg,#1a1a2e,#0f3460); }
  .stat-card { border:none; border-radius:14px; box-shadow:0 2px 12px rgba(0,0,0,.08); transition:transform .15s; }
  .stat-card:hover { transform:translateY(-3px); }
  .stat-icon { font-size:2.2rem; opacity:.85; }
  .table-card { border:none; border-radius:14px; box-shadow:0 2px 12px rgba(0,0,0,.08); overflow:hidden; }
  .table thead th { background:#1a1a2e; color:#fff; border:none; padding:12px 14px; font-weight:500; }
  .table tbody tr:hover { background:#f8f9ff; cursor:pointer; }
  .filter-bar { background:white; border-radius:12px; padding:16px 20px;
                box-shadow:0 2px 8px rgba(0,0,0,.05); margin-bottom:20px; }
  .btn-open { font-size:.78rem; padding:3px 10px; }
  .kw-badge { font-size:.68rem; background:#e8f4fd; color:#0d6efd; border-radius:4px;
              padding:2px 6px; margin:1px; display:inline-block; }
  .title-cell { max-width:320px; }
  .title-cell a { color:#1a1a2e; text-decoration:none; font-weight:500; }
  .title-cell a:hover { color:#0d6efd; text-decoration:underline; }
  .no-data { text-align:center; padding:60px 20px; color:#888; }
  @keyframes spin { to { transform:rotate(360deg); } }
  .spinning { animation:spin .8s linear infinite; }

  /* Detail panel */
  #detailPanel {
    position:fixed; top:0; right:-520px; width:500px; height:100vh;
    background:#fff; box-shadow:-4px 0 24px rgba(0,0,0,.15);
    transition:right .3s ease; z-index:1050; overflow-y:auto;
  }
  #detailPanel.open { right:0; }
  .panel-header { background:linear-gradient(135deg,#1a1a2e,#0f3460);
                  color:#fff; padding:18px 20px; position:sticky; top:0; z-index:1; }
  .info-row { display:flex; gap:8px; margin-bottom:10px; font-size:.88rem; }
  .info-label { color:#6c757d; min-width:120px; font-weight:500; flex-shrink:0; }
  .info-value { color:#1a1a2e; }
  .badge-startup { background:#d4edda; color:#155724; border-radius:6px;
                   padding:3px 10px; font-size:.78rem; font-weight:600; }
  .badge-no-startup { background:#f8d7da; color:#721c24; border-radius:6px;
                      padding:3px 10px; font-size:.78rem; }
  .scope-box { background:#f8f9fa; border-left:3px solid #0d6efd;
               padding:10px 14px; border-radius:0 6px 6px 0; font-size:.85rem;
               color:#333; margin-top:4px; }
  .startup-box { background:#f0fff4; border-left:3px solid #28a745;
                 padding:10px 14px; border-radius:0 6px 6px 0; font-size:.82rem;
                 color:#1a5e2a; margin-top:4px; line-height:1.5; }
  #panelOverlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,.3);
                  z-index:1040; }
  .loading-spinner { text-align:center; padding:60px 20px; color:#888; }
</style>
</head>
<body>

<nav class="navbar navbar-dark px-4 py-3 mb-4">
  <span class="navbar-brand fw-bold fs-5">
    <i class="bi bi-file-earmark-text me-2"></i>RFP Dashboard
  </span>
  <div class="d-flex align-items-center gap-3">
    <span class="text-white-50" style="font-size:.82rem">
      Last run: <strong class="text-white">{{ last_run }}</strong>
    </span>
    <button class="btn btn-sm btn-light" onclick="runAgent()" id="runBtn">
      <i class="bi bi-play-circle me-1"></i>Run Agent Now
    </button>
    <button class="btn btn-sm btn-outline-light" onclick="location.reload()" title="Refresh">
      <i class="bi bi-arrow-clockwise"></i>
    </button>
  </div>
</nav>

<div class="container-fluid px-4">

  <!-- Stats -->
  <div class="row g-3 mb-4">
    <div class="col-6 col-md-3">
      <div class="card stat-card p-3">
        <div class="d-flex justify-content-between align-items-center">
          <div><div class="text-muted small">Total RFPs</div>
               <div class="fw-bold fs-3">{{ stats.total }}</div></div>
          <i class="bi bi-collection stat-icon text-primary"></i>
        </div>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card stat-card p-3">
        <div class="d-flex justify-content-between align-items-center">
          <div><div class="text-muted small">Found Today</div>
               <div class="fw-bold fs-3 text-success">{{ stats.today }}</div></div>
          <i class="bi bi-calendar-check stat-icon text-success"></i>
        </div>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card stat-card p-3">
        <div class="d-flex justify-content-between align-items-center">
          <div><div class="text-muted small">Files Downloaded</div>
               <div class="fw-bold fs-3 text-warning">{{ stats.downloaded }}</div></div>
          <i class="bi bi-download stat-icon text-warning"></i>
        </div>
      </div>
    </div>
    <div class="col-6 col-md-3">
      <div class="card stat-card p-3">
        <div class="d-flex justify-content-between align-items-center">
          <div><div class="text-muted small">Active Sources</div>
               <div class="fw-bold fs-3 text-info">{{ stats.sources }}</div></div>
          <i class="bi bi-globe stat-icon text-info"></i>
        </div>
      </div>
    </div>
  </div>

  <!-- Filters -->
  <div class="filter-bar d-flex flex-wrap gap-3 align-items-end">
    <div class="flex-grow-1" style="min-width:200px">
      <label class="form-label small text-muted mb-1">Search</label>
      <input type="text" id="searchInput" class="form-control form-control-sm"
             placeholder="Title, source, keywords…" oninput="filterTable()">
    </div>
    <div style="min-width:190px">
      <label class="form-label small text-muted mb-1">Source</label>
      <select id="sourceFilter" class="form-select form-select-sm" onchange="filterTable()">
        <option value="">All Sources</option>
        {% for s in stats.source_list %}
        <option value="{{ s }}">{{ s }}</option>
        {% endfor %}
      </select>
    </div>
    <div style="min-width:140px">
      <label class="form-label small text-muted mb-1">Date</label>
      <select id="dateFilter" class="form-select form-select-sm" onchange="filterTable()">
        <option value="">All Time</option>
        <option value="today">Today</option>
        <option value="week">Last 7 Days</option>
        <option value="month">Last 30 Days</option>
      </select>
    </div>
    <div style="min-width:140px">
      <label class="form-label small text-muted mb-1">File</label>
      <select id="fileFilter" class="form-select form-select-sm" onchange="filterTable()">
        <option value="">All</option>
        <option value="yes">Downloaded</option>
        <option value="no">No File</option>
      </select>
    </div>
    <button class="btn btn-sm btn-outline-secondary" onclick="clearFilters()">
      <i class="bi bi-x-circle me-1"></i>Clear
    </button>
    <span class="ms-auto text-muted small align-self-center" id="rowCount"></span>
  </div>

  <!-- Table -->
  <div class="card table-card mb-5">
    {% if rfps %}
    <div class="table-responsive">
      <table class="table table-hover mb-0" id="rfpTable">
        <thead>
          <tr>
            <th style="width:130px">Date</th>
            <th>Title</th>
            <th style="width:190px">Source</th>
            <th style="width:150px">Keywords</th>
            <th style="width:110px" class="text-center">File</th>
            <th style="width:70px"  class="text-center">Link</th>
          </tr>
        </thead>
        <tbody id="tableBody">
          {% for r in rfps %}
          <tr data-source="{{ r.source|e }}"
              data-date="{{ r.date|e }}"
              data-file="{{ r.file|e }}"
              data-url="{{ r.url|e }}"
              data-title="{{ r.title|e }}"
              onclick="rowClick(this)">
            <td class="text-muted small align-middle">{{ r.date[:16] if r.date else '' }}</td>
            <td class="title-cell align-middle">
              <span class="fw-500" style="color:#1a1a2e">
                {{ r.title[:95] }}{% if r.title|length > 95 %}…{% endif %}
              </span>
            </td>
            <td class="align-middle">
              <span class="badge text-bg-secondary" style="font-size:.72rem">
                {{ r.source[:32] }}
              </span>
            </td>
            <td class="align-middle">
              {% for kw in r.keywords_matched.split(',') if r.keywords_matched %}
              <span class="kw-badge">{{ kw.strip() }}</span>
              {% endfor %}
            </td>
            <td class="text-center align-middle" onclick="event.stopPropagation()">
              {% if r.file %}
              <button class="btn btn-success btn-open"
                      data-file="{{ r.file|e }}"
                      data-url="{{ r.url|e }}"
                      data-title="{{ r.title|e }}"
                      onclick="showDetails(this.dataset.file, this.dataset.url, this.dataset.title)">
                <i class="bi bi-file-earmark-text me-1"></i>View
              </button>
              {% else %}
              <span class="text-muted">—</span>
              {% endif %}
            </td>
            <td class="text-center align-middle" onclick="event.stopPropagation()">
              {% if r.url %}
              <a href="{{ r.url }}" target="_blank"
                 class="btn btn-outline-primary btn-open">
                <i class="bi bi-box-arrow-up-right"></i>
              </a>
              {% else %}
              <span class="text-muted">—</span>
              {% endif %}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% else %}
    <div class="no-data">
      <i class="bi bi-inbox display-4 d-block mb-3 text-muted"></i>
      <h5 class="text-muted">No RFPs yet</h5>
      <p class="text-muted small">
        Click <strong>Run Agent Now</strong> to start fetching,<br>
        or wait for the daily scheduled run (7:00 AM).
      </p>
    </div>
    {% endif %}
  </div>
</div>

<!-- Detail Panel overlay -->
<div id="panelOverlay" onclick="closePanel()"></div>

<!-- Detail Panel -->
<div id="detailPanel">
  <div class="panel-header d-flex justify-content-between align-items-start">
    <div>
      <div class="small text-white-50 mb-1" id="panelDocType">—</div>
      <div class="fw-bold" id="panelRefNumber" style="font-size:.95rem">—</div>
    </div>
    <button class="btn btn-sm btn-outline-light ms-2 flex-shrink-0"
            onclick="closePanel()">
      <i class="bi bi-x-lg"></i>
    </button>
  </div>

  <div class="p-3">
    <!-- Action buttons -->
    <div class="d-flex gap-2 mb-3">
      <button class="btn btn-success btn-sm" id="btnOpenFile"
              onclick="openFileDirect()">
        <i class="bi bi-folder2-open me-1"></i>Open File
      </button>
      <a class="btn btn-outline-primary btn-sm" id="btnOpenUrl"
         target="_blank" href="#">
        <i class="bi bi-box-arrow-up-right me-1"></i>View on Portal
      </a>
    </div>

    <!-- Spinner shown while loading -->
    <div class="loading-spinner" id="panelSpinner">
      <div class="spinner-border text-primary mb-3" role="status"></div>
      <div>Reading document…</div>
    </div>

    <!-- Content shown after load -->
    <div id="panelContent" style="display:none">

      <!-- Key info grid -->
      <div class="mb-3">
        <div class="info-row">
          <span class="info-label"><i class="bi bi-building me-1"></i>Organisation</span>
          <span class="info-value" id="piOrg">—</span>
        </div>
        <div class="info-row">
          <span class="info-label"><i class="bi bi-diagram-3 me-1"></i>Ministry</span>
          <span class="info-value" id="piMinistry">—</span>
        </div>
        <div class="info-row">
          <span class="info-label"><i class="bi bi-tag me-1"></i>Category</span>
          <span class="info-value" id="piCategory">—</span>
        </div>
        <div class="info-row">
          <span class="info-label"><i class="bi bi-alarm me-1"></i>Deadline</span>
          <span class="info-value fw-bold text-danger" id="piDeadline">—</span>
        </div>
        <div class="info-row">
          <span class="info-label"><i class="bi bi-calendar3 me-1"></i>Contract</span>
          <span class="info-value" id="piContract">—</span>
        </div>
        <div class="info-row">
          <span class="info-label"><i class="bi bi-cash me-1"></i>EMD</span>
          <span class="info-value" id="piEmd">—</span>
        </div>
        <div class="info-row">
          <span class="info-label"><i class="bi bi-people me-1"></i>Vendor Slots</span>
          <span class="info-value" id="piVendor">—</span>
        </div>
        <div class="info-row">
          <span class="info-label"><i class="bi bi-envelope me-1"></i>Contact</span>
          <span class="info-value" id="piContact">—</span>
        </div>
      </div>

      <!-- Startup eligibility -->
      <div class="mb-3">
        <div class="small text-muted fw-500 mb-1">Startup / MSE Eligibility</div>
        <div id="piStartupBadge"></div>
        <div class="startup-box mt-2" id="piStartupNotes"
             style="display:none"></div>
      </div>

      <!-- Scope -->
      <div id="piScopeBlock" style="display:none">
        <div class="small text-muted fw-500 mb-1">Scope of Work</div>
        <div class="scope-box" id="piScope"></div>
      </div>

    </div><!-- /panelContent -->
  </div>
</div>

<!-- Toast -->
<div class="toast-container position-fixed bottom-0 end-0 p-3">
  <div id="toast" class="toast text-bg-primary border-0">
    <div class="d-flex">
      <div class="toast-body" id="toastText"></div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto"
              data-bs-dismiss="toast"></button>
    </div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
const rows = document.querySelectorAll('#tableBody tr');
let currentFilePath = '';

// ── Filtering ─────────────────────────────────────────────────────────────────
function filterTable() {
  const q     = document.getElementById('searchInput').value.toLowerCase();
  const src   = document.getElementById('sourceFilter').value.toLowerCase();
  const dateF = document.getElementById('dateFilter').value;
  const fileF = document.getElementById('fileFilter').value;
  const now   = new Date();
  let vis = 0;
  rows.forEach(row => {
    const text  = row.textContent.toLowerCase();
    const rSrc  = (row.dataset.source || '').toLowerCase();
    const rDate = row.dataset.date || '';
    const rFile = (row.dataset.file || '').trim();
    let show = true;
    if (q    && !text.includes(q))       show = false;
    if (src  && !rSrc.includes(src))     show = false;
    if (fileF === 'yes' && !rFile)       show = false;
    if (fileF === 'no'  &&  rFile)       show = false;
    if (dateF && rDate) {
      const d = new Date(rDate);
      if (dateF === 'today') {
        const t = new Date(); t.setHours(0,0,0,0); if (d < t) show = false;
      } else if (dateF === 'week')  { if (d < new Date(now - 7*864e5))  show = false; }
      else if (dateF === 'month')   { if (d < new Date(now - 30*864e5)) show = false; }
    }
    row.style.display = show ? '' : 'none';
    if (show) vis++;
  });
  document.getElementById('rowCount').textContent = vis + ' of ' + rows.length + ' RFPs';
}

function clearFilters() {
  ['searchInput','sourceFilter','dateFilter','fileFilter']
    .forEach(id => document.getElementById(id).value = '');
  filterTable();
}

// ── Row click — open panel if file exists ─────────────────────────────────────
function rowClick(row) {
  const file = (row.dataset.file || '').trim();
  const url  = row.dataset.url || '';
  const title = row.dataset.title || '';
  if (file) showDetails(file, url, title);
}

// ── Detail panel ──────────────────────────────────────────────────────────────
function showDetails(filePath, url, title) {
  currentFilePath = filePath;

  // Set URL button
  const urlBtn = document.getElementById('btnOpenUrl');
  if (url) { urlBtn.href = url; urlBtn.style.display = ''; }
  else     { urlBtn.style.display = 'none'; }

  // Reset panel state
  document.getElementById('panelSpinner').style.display = '';
  document.getElementById('panelContent').style.display = 'none';
  document.getElementById('panelRefNumber').textContent  = title || '…';
  document.getElementById('panelDocType').textContent    = '';

  // Open panel
  document.getElementById('detailPanel').classList.add('open');
  document.getElementById('panelOverlay').style.display = '';

  // Fetch extracted info
  fetch('/rfp-info', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({path: filePath})
  })
  .then(r => r.json())
  .then(d => populatePanel(d))
  .catch(e => {
    document.getElementById('panelSpinner').style.display = 'none';
    document.getElementById('panelContent').innerHTML =
      '<div class="text-danger p-3">Could not read document: ' + e + '</div>';
    document.getElementById('panelContent').style.display = '';
  });
}

function populatePanel(d) {
  document.getElementById('panelSpinner').style.display = 'none';
  document.getElementById('panelContent').style.display = '';

  set('panelDocType',  d.doc_type    || '');
  set('panelRefNumber', d.ref_number  || document.getElementById('panelRefNumber').textContent);
  set('piOrg',         d.organization || '—');
  set('piMinistry',    d.ministry     || '—');
  set('piCategory',    d.category     || '—');
  set('piDeadline',    d.deadline     || '—');
  set('piContract',    d.contract_period || '—');
  set('piEmd',         d.emd          || '—');
  set('piVendor',      d.vendor_panel_size || '—');
  set('piContact',     d.contact      || '—');

  // Startup badge
  const badge = document.getElementById('piStartupBadge');
  if (d.startup_eligible) {
    badge.innerHTML = '<span class="badge-startup"><i class="bi bi-check-circle-fill me-1"></i>Startup / MSE Eligible</span>';
  } else {
    badge.innerHTML = '<span class="badge-no-startup"><i class="bi bi-x-circle me-1"></i>No startup clause detected</span>';
  }
  const notesEl = document.getElementById('piStartupNotes');
  if (d.startup_notes) {
    notesEl.textContent = d.startup_notes;
    notesEl.style.display = '';
  } else {
    notesEl.style.display = 'none';
  }

  // Scope
  const scopeBlock = document.getElementById('piScopeBlock');
  if (d.scope_summary) {
    document.getElementById('piScope').textContent = d.scope_summary;
    scopeBlock.style.display = '';
  } else {
    scopeBlock.style.display = 'none';
  }

  if (d.error) {
    document.getElementById('panelContent').insertAdjacentHTML('beforeend',
      '<div class="alert alert-warning mt-3 small">' + d.error + '</div>');
  }
}

function set(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function closePanel() {
  document.getElementById('detailPanel').classList.remove('open');
  document.getElementById('panelOverlay').style.display = 'none';
}

function openFileDirect() {
  if (!currentFilePath) return;
  fetch('/open-file', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({path: currentFilePath})
  })
  .then(r => r.json())
  .then(d => toast(d.message));
}

// ── Agent ────────────────────────────────────────────────────────────────────
function runAgent() {
  const btn = document.getElementById('runBtn');
  btn.disabled = true;
  btn.innerHTML = '<i class="bi bi-hourglass-split me-1 spinning"></i>Running…';
  toast('Agent started — fetching RFPs…');
  fetch('/run-agent', {method:'POST'})
  .then(r => r.json()).then(d => {
    toast(d.message);
    setTimeout(() => location.reload(), 8000);
  }).catch(() => {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-play-circle me-1"></i>Run Agent Now';
  });
}

function toast(msg) {
  document.getElementById('toastText').textContent = msg;
  bootstrap.Toast.getOrCreateInstance(
    document.getElementById('toast'), {delay:4000}).show();
}

filterTable();
setTimeout(() => location.reload(), 300000);
</script>
</body>
</html>
"""


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    rfps     = load_rfps()
    stats    = get_stats(rfps)
    last_run = get_last_run()
    return render_template_string(TEMPLATE, rfps=rfps, stats=stats, last_run=last_run)


@app.route("/rfp-info", methods=["POST"])
def rfp_info():
    path = (request.get_json() or {}).get("path", "")
    # Resolve relative paths from project root
    p = Path(path)
    if not p.is_absolute():
        p = ROOT_DIR / p
    if not p.exists():
        return jsonify({"error": f"File not found: {p.name}"})
    try:
        info = extract_rfp_info(str(p))
        info.pop("raw_text", None)   # don't send full text to browser
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/open-file", methods=["POST"])
def open_file():
    path = (request.get_json() or {}).get("path", "")
    p = Path(path)
    if not p.is_absolute():
        p = ROOT_DIR / p
    if not p.exists():
        return jsonify({"message": f"File not found: {p.name}"})
    try:
        os.startfile(str(p))
        return jsonify({"message": f"Opened: {p.name}"})
    except Exception as e:
        return jsonify({"message": f"Error: {e}"})


@app.route("/run-agent", methods=["POST"])
def run_agent():
    script = ROOT_DIR / "run_agent.py"
    try:
        subprocess.Popen(
            ["python", str(script)],
            cwd=str(ROOT_DIR),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return jsonify({"message": "Agent running — page will refresh shortly."})
    except Exception as e:
        return jsonify({"message": f"Failed: {e}"})
