"""Jinja2 templates of the web interface (autoescaped, no external assets)."""

BASE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#1F3864">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" href="/icon.svg" type="image/svg+xml">
<title>{% block title %}FIN TAX PRO{% endblock %}</title>
<style>
:root{--navy:#1F3864;--teal:#00897B;--bg:#F4F7FA;--card:#fff;--text:#1B2631;--muted:#546E7A;--line:#DDE3EA;
--red:#C62828;--redbg:#FFCDD2;--amber:#8D6E00;--amberbg:#FFF3C4;--green:#2E7D32;--greenbg:#C8E6C9;--greybg:#ECEFF1}
@media (prefers-color-scheme:dark){:root{--bg:#0F1720;--card:#17212B;--text:#E3E8EE;--muted:#9AA9B5;--line:#2A3743;
--redbg:#4A1C1C;--amberbg:#463A10;--greenbg:#1C3B22;--greybg:#26313C;--red:#FF8A80;--amber:#FFD54F;--green:#81C784}}
*{box-sizing:border-box}body{margin:0;font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
background:var(--bg);color:var(--text)}
header{background:var(--navy);color:#fff;padding:12px 16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
header a{color:#fff;text-decoration:none}header .brand{font-weight:700;letter-spacing:.3px}
header .sp{flex:1}header .who{font-size:13px;opacity:.85}
main{max-width:1100px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:4px 0 2px}h2{font-size:16px;margin:22px 0 8px;color:var(--teal)}
.muted{color:var(--muted);font-size:13px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.card .k{font-size:12px;color:var(--muted)}.card .v{font-size:19px;font-weight:700;margin-top:2px}
a.client{display:block;color:inherit;text-decoration:none}
.list{display:grid;gap:10px}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600}
.red{background:var(--redbg);color:var(--red)}.amber{background:var(--amberbg);color:var(--amber)}
.green{background:var(--greenbg);color:var(--green)}.grey{background:var(--greybg);color:var(--muted)}
.tbl{width:100%;overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:7px 9px;border-bottom:1px solid var(--line);
text-align:left;vertical-align:top}th{background:var(--navy);color:#fff;font-weight:600;position:sticky;top:0}
td.n,th.n{text-align:right;white-space:nowrap}
.btn{display:inline-block;background:var(--teal);color:#fff;border:0;border-radius:8px;padding:9px 14px;
text-decoration:none;font-weight:600;font-size:14px;cursor:pointer}
.btn.alt{background:transparent;color:var(--teal);border:1px solid var(--teal)}
form.inline{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
input,select{font:inherit;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);
color:var(--text)}
.login{max-width:360px;margin:40px auto}.login input{width:100%;margin:6px 0 12px}
.err{background:var(--redbg);color:var(--red);padding:8px 10px;border-radius:8px}
ul.issues{margin:4px 0 0;padding-left:18px;font-size:13px}
footer{color:var(--muted);font-size:12px;text-align:center;padding:24px 16px}
</style></head><body>
<header><a class="brand" href="/">FIN TAX PRO</a><span class="muted" style="color:#cfd8dc">GST reconciliation</span>
<span class="sp"></span>{% if user %}<span class="who">{{ user.full_name or user.username }} · {{ role }}</span>
{% if can_upload %}<a href="/upload">Upload</a>{% endif %}<a href="/logout">Log out</a>{% endif %}</header>
<main>{% block body %}{% endblock %}</main>
<footer>{% if can_upload %}Uploads are previewed before saving · {% endif %}every change is recorded with your
name · data stays on the firm's computer · no portal access</footer>
</body></html>"""

LOGIN = """{% extends "base" %}{% block title %}Log in · FIN TAX PRO{% endblock %}{% block body %}
<div class="login card"><h1>Log in</h1><p class="muted">Use your FIN TAX PRO user name and password.</p>
{% if error %}<p class="err">{{ error }}</p>{% endif %}
<form method="post" action="/login"><label>User name<input name="username" autocomplete="username" required
autofocus></label><label>Password<input name="password" type="password" autocomplete="current-password" required>
</label><button class="btn" type="submit">Log in</button></form></div>{% endblock %}"""

DASHBOARD = """{% extends "base" %}{% block title %}Annual dashboard · FIN TAX PRO{% endblock %}{% block body %}
<div class="row"><div style="flex:1"><h1>Annual GST reconciliation dashboard</h1>
<div class="muted">FY {{ fy }} · {{ clients|length }} client(s)</div></div>
<form class="inline" method="get"><select name="fy">{% for f in fys %}<option {% if f == fy %}selected{% endif %}>
{{ f }}</option>{% endfor %}</select><button class="btn alt">Show</button></form>
{% if can_export %}<a class="btn" href="/dashboard.xlsx?fy={{ fy }}">Excel</a>{% endif %}</div>
<div class="cards" style="margin-top:12px">
<div class="card"><div class="k">Action required</div><div class="v">{{ counts.red }}</div></div>
<div class="card"><div class="k">Attention</div><div class="v">{{ counts.amber }}</div></div>
<div class="card"><div class="k">Reconciled</div><div class="v">{{ counts.green }}</div></div>
<div class="card"><div class="k">Pending exceptions</div><div class="v">{{ pending }}</div></div></div>
{% if upcoming %}<h2>Returns due</h2><div class="tbl"><table><tr><th>Due</th><th>Return</th><th>Client</th>
<th>Data</th></tr>{% for u in upcoming %}<tr><td>{{ u.item.due.strftime("%d-%m-%Y") }}</td><td>{{ u.item.return_type }}
<div class="muted">{{ u.item.period }}{% if u.item.extended %} · {{ u.item.basis }}{% endif %}</div></td>
<td>{{ u.client }}</td><td>{% if u.overdue %}<span class="pill red">Overdue</span>{% elif u.status == "imported" %}
<span class="pill green">Imported</span>{% else %}<span class="pill grey">{{ u.status }}</span>{% endif %}</td></tr>
{% endfor %}</table></div>{% endif %}
<h2>Clients</h2><div class="list">{% for c in clients %}
<a class="client card" href="/client/{{ c.client_id }}?fy={{ fy }}"><div class="row"><b style="flex:1">{{ c.name }}</b>
<span class="pill {{ c.rag }}">{{ rag[c.rag] }}</span></div><div class="muted">{{ c.gstin }} · {{ c.months_with_data }}
month(s) with data · {{ c.pending }} pending · ITC at risk ₹{{ money(c.total("itc_at_risk")) }}
{% if c.total("short_payment") %} · possible short payment ₹{{ money(c.total("short_payment")) }}{% endif %}</div></a>
{% else %}<p class="muted">No clients.</p>{% endfor %}</div>{% endblock %}"""

CLIENT = """{% extends "base" %}{% block title %}{{ c.name }} · FIN TAX PRO{% endblock %}{% block body %}
<div class="row"><div style="flex:1"><h1>{{ c.name }}</h1><div class="muted">GSTIN {{ c.gstin }} · FY {{ c.fy }}</div>
</div><span class="pill {{ c.rag }}">{{ rag[c.rag] }}</span>
{% if can_export %}<a class="btn" href="/client/{{ c.client_id }}/compliance.pdf?fy={{ c.fy }}">Compliance PDF</a>
<a class="btn alt" href="/client/{{ c.client_id }}/gstr9.xlsx?fy={{ c.fy }}">GSTR-9 working</a>{% endif %}
<a class="btn alt" href="/client/{{ c.client_id }}/ledgers?fy={{ c.fy }}">Ledger classification</a>
<a class="btn alt" href="/client/{{ c.client_id }}/itc?fy={{ c.fy }}">ITC classification</a></div>
<div class="cards" style="margin-top:12px">
<div class="card"><div class="k">Months with data</div><div class="v">{{ c.months_with_data }}</div></div>
<div class="card"><div class="k">Pending exceptions</div><div class="v">{{ c.pending }}</div></div>
<div class="card"><div class="k">ITC at risk</div><div class="v">₹{{ money(c.total("itc_at_risk")) }}</div></div>
<div class="card"><div class="k">3B ITC above 2B</div><div class="v">₹{{ money(c.total("itc_excess")) }}</div></div>
<div class="card"><div class="k">Possible short payment</div><div class="v">₹{{ money(c.total("short_payment")) }}</div>
</div><div class="card"><div class="k">Follow-ups due</div><div class="v">{{ c.followups_due }}</div></div></div>
<h2>Month status</h2><div class="tbl"><table><tr><th>Month</th><th>Status</th><th class="n">ITC 2B</th>
<th class="n">ITC 3B</th><th class="n">Output GSTR-1</th><th class="n">Output 3B</th><th>Runs</th><th>Issues</th></tr>
{% for m in c.months if m.has_data %}<tr><td>{{ m.period }}</td><td><span class="pill {{ m.rag }}">{{ rag[m.rag] }}</span>
</td><td class="n">{{ money(m.itc_2b) if m.inward else "" }}</td><td class="n">{{ money(m.itc_3b) }}</td>
<td class="n">{{ money(m.output_gstr1) }}</td><td class="n">{{ money(m.output_3b) }}</td>
<td>{% if m.inward_run_id %}<a href="/run/{{ m.inward_run_id }}">Purchases</a>{% endif %}
{% if m.outward_run_id %}<a href="/run/{{ m.outward_run_id }}">Sales</a>{% endif %}</td>
<td><ul class="issues">{% for r, t in m.issues %}<li>{{ t }}</li>{% endfor %}</ul></td></tr>
{% else %}<tr><td colspan="8" class="muted">No data imported for this year.</td></tr>{% endfor %}</table></div>
<h2>All reconciliation runs</h2><div class="tbl"><table><tr><th>Run</th><th>Period</th><th>Comparison</th>
<th>When</th><th>By</th></tr>{% for r in runs %}<tr><td><a href="/run/{{ r.id }}">#{{ r.id }}</a></td>
<td>{{ r.period_from }}{% if r.period_to != r.period_from %} – {{ r.period_to }}{% endif %}</td>
<td>{{ r.comparison.replace("_", " ") }}</td><td>{{ r.started_at.strftime("%d-%m-%Y %H:%M") }}</td>
<td>{{ r.created_by }}</td></tr>{% endfor %}</table></div>{% endblock %}"""

RUN = """{% extends "base" %}{% block title %}Run {{ run.id }} · FIN TAX PRO{% endblock %}{% block body %}
<div class="row"><div style="flex:1"><h1>{{ client.name }}</h1><div class="muted">{{ left }} vs {{ right }} ·
{{ run.period_from }}{% if run.period_to != run.period_from %} – {{ run.period_to }}{% endif %} · run #{{ run.id }}
</div></div>{% if can_export %}<a class="btn" href="/run/{{ run.id }}/report.xlsx">Excel report</a>
<a class="btn alt" href="/run/{{ run.id }}/report.pdf">PDF</a>{% endif %}</div>
<div class="cards" style="margin-top:12px">{% for label, value in cards %}<div class="card"><div class="k">{{ label }}
</div><div class="v">{{ value }}</div></div>{% endfor %}</div>
{% if liability %}<h2>GSTR-1 vs GSTR-3B (Table 3.1)</h2>{% for w in liability %}<div class="tbl"><table><tr>
<th>{{ w.period }}</th><th class="n">GSTR-1 tax</th><th class="n">Sales tax</th><th class="n">3B tax</th>
<th class="n">3B − GSTR-1</th></tr>{% for r in w.rows %}<tr><td>{{ r.label }}</td><td class="n">{{ money(r.gstr1.total) }}
</td><td class="n">{{ money(r.sales.total) }}</td><td class="n">{{ money(r.filed.total) if r.filed else "" }}</td>
<td class="n">{{ money(r.diff_filed_gstr1) }}</td></tr>{% endfor %}</table></div>
<ul class="issues">{% for f in w.findings %}<li><b>{{ f.severity|upper }}</b> {{ f.text }}</li>{% endfor %}</ul>
{% endfor %}{% endif %}
<h2>Categories</h2><div class="tbl"><table><tr><th>Category</th><th class="n">Lines</th><th class="n">{{ left }} tax
</th><th class="n">{{ right }} tax</th></tr>{% for r in categories %}<tr><td>{{ r[0] }}</td><td class="n">{{ r[1] }}</td>
<td class="n">{{ money(r[2]) }}</td><td class="n">{{ money(r[3]) }}</td></tr>{% endfor %}</table></div>
<h2>{{ party }}s</h2><div class="tbl"><table><tr><th>{{ party }}</th><th class="n">{{ left }} tax</th>
<th class="n">{{ right }} tax</th><th class="n">Difference</th><th class="n">Unresolved</th></tr>
{% for s in suppliers %}<tr><td>{{ s.name or s.gstin }}<div class="muted">{{ s.gstin }}</div></td>
<td class="n">{{ money(s.books.itc) }}</td><td class="n">{{ money(s.gstr2b.itc) }}</td>
<td class="n">{{ money(s.itc_difference) }}</td><td class="n">{{ s.unresolved }}</td></tr>{% endfor %}</table></div>
<h2>Pending exceptions ({{ pending_total }})</h2><div class="tbl"><table><tr><th>#</th><th>{{ party }}</th>
<th>Document</th><th>Category</th><th class="n">Tax</th><th>Status</th></tr>{% for ln, r in pending %}<tr>
<td>{{ ln.line_no }}</td><td>{{ r.supplier_name or r.supplier_gstin }}</td><td>{{ r.invoice_no }}
<div class="muted">{{ r.invoice_date.strftime("%d-%m-%Y") if r.invoice_date else "" }}</div></td>
<td>{{ relabel(ln.category.value) }}</td><td class="n">{{ money(r.total_tax) }}</td><td>{{ ln.status.value }}
{% if ln.remarks %}<div class="muted">{{ ln.remarks }}</div>{% endif %}</td></tr>{% endfor %}</table></div>
{% if pending_total > pending|length %}<p class="muted">First {{ pending|length }} shown – the Excel report has all.
</p>{% endif %}{% endblock %}"""

UPLOAD = """{% extends "base" %}{% block title %}Upload · FIN TAX PRO{% endblock %}{% block body %}
<h1>Upload a file</h1><p class="muted">The file is checked first; nothing is saved until you confirm the preview.
If the headings are not recognised you can map the columns on the next screen.</p>
{% if error %}<p class="err">{{ error }}</p>{% endif %}
<form class="card" method="post" action="/upload" enctype="multipart/form-data" style="display:grid;gap:10px">
<input type="hidden" name="csrf" value="{{ csrf }}">
<label>Client<br><select name="client_id" required>{% for c in clients %}<option value="{{ c.id }}"
{% if c.id == client_id %}selected{% endif %}>{{ c.name }} · {{ c.gstin }}</option>{% endfor %}</select></label>
<label>File type<br><select name="source">{% for k, v in sources %}<option value="{{ k }}">{{ v }}</option>
{% endfor %}</select></label>
<label>Period (YYYY-MM, only if the file does not state it)<br><input name="period" placeholder="2025-04"
pattern="\\d{4}-\\d{2}"></label>
<label>File (Excel, CSV, JSON or ZIP, up to {{ max_mb }} MB)<br><input type="file" name="file" required
accept=".xlsx,.xlsm,.xls,.csv,.json,.zip,.xml"></label>
<button class="btn" type="submit">Check file</button></form>{% endblock %}"""

UPLOAD_PREVIEW = """{% extends "base" %}{% block title %}Preview · FIN TAX PRO{% endblock %}{% block body %}
<h1>Check before saving</h1><div class="muted">{{ client.name }} · {{ file_name }} · {{ layout }}
{% if period %} · period {{ period }}{% endif %}</div>
<div class="cards" style="margin-top:12px">{% for label, value in figures %}<div class="card"><div class="k">{{ label }}
</div><div class="v">{{ value }}</div></div>{% endfor %}</div>
{% if warnings %}<h2>Warnings</h2><ul class="issues">{% for w in warnings %}<li>{{ w }}</li>{% endfor %}</ul>{% endif %}
{% if issues %}<h2>Rows needing attention (first {{ issues|length }})</h2><div class="tbl"><table><tr><th>Sheet</th>
<th>Row</th><th>Type</th><th>Message</th></tr>{% for i in issues %}<tr><td>{{ i.sheet }}</td><td>{{ i.row }}</td>
<td>{{ i.severity }}</td><td>{{ i.message }}</td></tr>{% endfor %}</table></div>{% endif %}
{% if blocked %}<p class="err">{{ blocked }}</p>{% endif %}
<div class="row" style="margin-top:14px">{% if not blocked %}<form method="post" action="/upload/{{ token }}/commit">
<input type="hidden" name="csrf" value="{{ csrf }}"><button class="btn" type="submit">Save import</button></form>
{% endif %}<form method="post" action="/upload/{{ token }}/discard"><input type="hidden" name="csrf" value="{{ csrf }}">
<button class="btn alt" type="submit">Discard</button></form></div>{% endblock %}"""

MAPPING = """{% extends "base" %}{% block title %}Map columns · FIN TAX PRO{% endblock %}{% block body %}
<h1>Map the columns</h1><div class="muted">{{ file_name }} · {{ where }} – the headings were not recognised.
Choose the file column for each field; amounts may combine several columns (hold Ctrl or long-press).</div>
{% if error %}<p class="err">{{ error }}</p>{% endif %}
<form class="card" method="post" action="/upload/{{ token }}/map" style="display:grid;gap:10px;margin-top:12px">
<input type="hidden" name="csrf" value="{{ csrf }}">
{% for f, label, required, multi in fields %}<label>{{ label }}{% if required %} <b>*</b>{% endif %}<br>
<select name="f_{{ f }}" {% if multi %}multiple size="3"{% endif %} style="width:100%">
{% if not multi %}<option value="">—</option>{% endif %}
{% for c in columns %}<option value="{{ c }}" {% if c in current.get(f, []) %}selected{% endif %}>{{ c }}</option>
{% endfor %}</select></label>{% endfor %}
<label>Save this mapping as a template (optional)<br><input name="template_name" placeholder="e.g. Client X register"
maxlength="80"></label>
<div class="row"><button class="btn" type="submit">Check file with this mapping</button></div></form>
<form method="post" action="/upload/{{ token }}/discard" style="margin-top:10px"><input type="hidden" name="csrf"
value="{{ csrf }}"><button class="btn alt" type="submit">Discard</button></form>{% endblock %}"""

DONE = """{% extends "base" %}{% block title %}Saved · FIN TAX PRO{% endblock %}{% block body %}
<h1>{{ title }}</h1><p>{{ message }}</p><p><a class="btn" href="/client/{{ client_id }}">Open client</a>
<a class="btn alt" href="/upload">Upload another file</a></p>{% endblock %}"""

LEDGERS = """{% extends "base" %}{% block title %}Ledgers · {{ cname }}{% endblock %}{% block body %}
<div class="row"><div style="flex:1"><h1>Ledger classification</h1><div class="muted"><a href="/client/{{ client_id }}?fy=
{{ fy }}">{{ cname }}</a> · {{ gstin }} · FY {{ fy }}</div></div>
<form class="inline" method="get"><input type="hidden" name="fy" value="{{ fy }}"><select name="show">
<option value="todo" {% if show == "todo" %}selected{% endif %}>To do</option><option value="all"
{% if show == "all" %}selected{% endif %}>All ledgers</option></select><button class="btn alt">Show</button></form>
{% if can_edit %}<form method="post" action="/client/{{ client_id }}/ledgers/action"><input type="hidden" name="csrf"
value="{{ csrf }}"><input type="hidden" name="fy" value="{{ fy }}"><input type="hidden" name="show" value="{{ show }}">
<button class="btn" name="action" value="suggest">Suggest classifications</button></form>{% endif %}</div>
{% if msg %}<p class="card">{{ msg }}</p>{% endif %}
<p><span class="pill {{ 'green' if ok else 'amber' }}">{{ "Ready for GSTR-9 / 9C" if ok else "Not ready" }}</span>
<span class="muted">{{ reasons|join("; ") }}</span></p>
<div class="cards"><div class="card"><div class="k">Ledgers to classify</div><div class="v">{{ sm.in_scope|length }}
</div></div><div class="card"><div class="k">Approved</div><div class="v">{{ sm.count("Approved") }}</div></div>
<div class="card"><div class="k">Suggested</div><div class="v">{{ sm.count("Suggested") }}</div></div>
<div class="card"><div class="k">Unallocated</div><div class="v">₹{{ money(sm.unallocated) }}</div></div></div>
<h2>{{ total }} ledger(s)</h2><div class="list">{% for v in views %}<div class="card">
<div class="row"><b style="flex:1">{{ v.ledger.name }}</b><span class="pill {{ 'green' if v.state == 'Approved' else
'amber' if v.state.startswith('Suggested') else 'red' }}">{{ v.state }}</span></div>
<div class="muted">{{ v.ledger.parent or v.ledger.primary_group }} · ₹{{ money(v.ledger.base) }}
{% if v.splits %} · {{ v.label("acct_class") }} · {{ v.label("gst_class") }} · {{ v.label("eligibility") }}{% endif %}
{% for w in v.warnings %}<br>⚠ {{ w }}{% endfor %}</div>
{% if can_edit %}<form class="inline" method="post" action="/client/{{ client_id }}/ledgers/action" style="margin-top:8px">
<input type="hidden" name="csrf" value="{{ csrf }}"><input type="hidden" name="fy" value="{{ fy }}">
<input type="hidden" name="show" value="{{ show }}"><input type="hidden" name="ledger_id" value="{{ v.ledger.id }}">
{% if v.state.startswith("Suggested") %}<button class="btn" name="action" value="approve">Approve</button>{% endif %}
<select name="acct_class">{% for a in acct_classes %}<option {% if v.splits and v.splits[0].acct_class == a %}selected
{% endif %}>{{ a }}</option>{% endfor %}</select><select name="gst_class">{% for k, l in gst_classes.items() %}<option
value="{{ k }}" {% if v.splits and v.splits[0].gst_class == k %}selected{% endif %}>{{ l }}</option>{% endfor %}</select>
<select name="eligibility"><option value="">(eligibility)</option>{% for k, l in eligibility.items() %}<option
value="{{ k }}" {% if v.splits and v.splits[0].eligibility == k %}selected{% endif %}>{{ l }}</option>{% endfor %}
</select><button class="btn alt" name="action" value="classify">Classify whole</button></form>
<div class="muted">Splitting a ledger into parts is done in the desktop program.</div>{% endif %}</div>
{% else %}<p class="muted">Nothing to do{% if not sm.views %} – no trial balance imported for {{ fy }}{% endif %}.</p>
{% endfor %}</div>{% endblock %}"""

ITC = """{% extends "base" %}{% block title %}ITC · {{ cname }}{% endblock %}{% block body %}
<div class="row"><div style="flex:1"><h1>ITC classification</h1><div class="muted"><a href="/client/{{ client_id }}?fy=
{{ fy }}">{{ cname }}</a> · {{ gstin }} · FY {{ fy }}</div></div>
<form class="inline" method="get"><input type="hidden" name="fy" value="{{ fy }}"><select name="show">
<option value="review" {% if show == "review" %}selected{% endif %}>To review</option>
<option value="unverified" {% if show == "unverified" %}selected{% endif %}>Claim not verified</option>
<option value="all" {% if show == "all" %}selected{% endif %}>All</option></select><input name="q" value="{{ q }}"
placeholder="Supplier, GSTIN, invoice"><button class="btn alt">Show</button></form></div>
{% if msg %}<p class="card">{{ msg }}</p>{% endif %}
<div class="cards"><div class="card"><div class="k">Transactions</div><div class="v">{{ w.txns|length }}</div></div>
<div class="card"><div class="k">Unclassified</div><div class="v">{{ w.unclassified }}</div></div>
<div class="card"><div class="k">To review</div><div class="v">{{ w.to_review }}</div></div>
<div class="card"><div class="k">Claim not verified</div><div class="v">{{ w.by_claim.get("unknown").count if
w.by_claim.get("unknown") else 0 }}</div></div></div>
<p class="muted">Classification and eligibility are not the claim: record what was done in GSTR-3B separately.</p>
<h2>{{ total }} transaction(s){% if total > views|length %} – first {{ views|length }}{% endif %}</h2>
<div class="list">{% for v in views %}{% set p = v.parts[0] %}<div class="card">
<div class="row"><b style="flex:1">{{ v.txn.party }}</b><span class="muted">₹{{ money(v.tax) }}</span></div>
<div class="muted">{{ v.txn.invoice_no or v.txn.voucher_no }} · {{ v.txn.voucher_date.strftime("%d-%m-%Y") if
v.txn.voucher_date else "" }} · {{ v.txn.gstin }}{% if v.txn.ledger %} · {{ v.txn.ledger }}{% endif %}<br>
{{ v.label("nature") }} · {{ v.label("treatment") }} · {{ v.label("status") }} · <b>{{ v.label("claim") }}
{{ p.claim_period if p else "" }}</b> · {{ v.label("confidence") }}</div>
{% if can_edit and v.parts|length == 1 %}<form class="inline" method="post" action="/client/{{ client_id }}/itc/action"
style="margin-top:8px"><input type="hidden" name="csrf" value="{{ csrf }}"><input type="hidden" name="fy" value="{{ fy
}}"><input type="hidden" name="show" value="{{ show }}"><input type="hidden" name="txn_id" value="{{ v.txn.id }}">
<select name="nature">{% for k, l in natures.items() %}<option value="{{ k }}" {% if p.nature == k %}selected{% endif %}>
{{ l }}</option>{% endfor %}</select><select name="treatment">{% for k, l in treatments.items() %}<option value="{{ k }}"
{% if p.treatment == k %}selected{% endif %}>{{ l }}</option>{% endfor %}</select><select name="status">{% for k, l in
statuses.items() %}<option value="{{ k }}" {% if p.status == k %}selected{% endif %}>{{ l }}</option>{% endfor %}
</select><button class="btn alt" name="action" value="classify">Save classification</button></form>{% endif %}
{% if can_claim %}<form class="inline" method="post" action="/client/{{ client_id }}/itc/action" style="margin-top:6px">
<input type="hidden" name="csrf" value="{{ csrf }}"><input type="hidden" name="fy" value="{{ fy }}"><input type="hidden"
name="show" value="{{ show }}"><input type="hidden" name="txn_id" value="{{ v.txn.id }}"><select name="claim">{% for k, l
in claims.items() %}<option value="{{ k }}" {% if p and p.claim == k %}selected{% endif %}>{{ l }}</option>{% endfor %}
</select><input name="period" value="{{ p.claim_period if p and p.claim_period else v.txn.period }}" size="8"
placeholder="YYYY-MM"><button class="btn alt" name="action" value="claim">Record claim</button></form>{% endif %}
</div>{% else %}<p class="muted">Nothing to show{% if not w.views %} – build the register in the desktop program
first{% endif %}.</p>{% endfor %}</div>{% endblock %}"""


TEMPLATES = {"ledgers": LEDGERS, "itc": ITC, "mapping": MAPPING, "upload": UPLOAD, "upload_preview": UPLOAD_PREVIEW, "done": DONE, "base": BASE, "login": LOGIN, "dashboard": DASHBOARD, "client": CLIENT, "run": RUN}

ICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14"
fill="#1F3864"/><rect x="10" y="46" width="44" height="6" fill="#00897B"/><text x="32" y="38" font-family="Arial"
font-size="24" font-weight="bold" fill="#fff" text-anchor="middle">FT</text></svg>"""
