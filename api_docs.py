"""
Friendly, product-style API documentation page (served at GET /).

Self-contained HTML (inline CSS + JS, no external dependencies) aimed at BOTH
non-technical readers (plain explanations, how-it-works, glossary) and
developers (copy-able request/response examples for every endpoint).

The interactive Swagger playground stays at /docs.
"""

LANDING_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Call Review AI — Documentation</title>
<style>
  :root{
    --bg:#f7f8fb; --panel:#ffffff; --ink:#1f2733; --muted:#64748b; --line:#e6e9ef;
    --brand:#3b5bdb; --brand-soft:#eef1fe; --accent:#0ea5e9;
    --get:#16a34a; --post:#2563eb; --put:#d97706; --code:#0b1220; --code-ink:#e6edf6;
    --radius:14px; --maxw:1180px;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;line-height:1.6}
  a{color:var(--brand);text-decoration:none} a:hover{text-decoration:underline}
  code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}

  /* layout */
  .wrap{max-width:var(--maxw);margin:0 auto;display:grid;grid-template-columns:248px 1fr;gap:36px;padding:0 22px}
  nav.side{position:sticky;top:0;align-self:start;height:100vh;overflow:auto;padding:26px 8px 40px}
  nav.side .brand{font-weight:800;font-size:18px;margin:0 8px 14px;color:var(--ink)}
  nav.side a{display:block;color:var(--muted);padding:6px 10px;border-radius:8px;font-size:14px}
  nav.side a:hover{background:var(--brand-soft);text-decoration:none;color:var(--ink)}
  nav.side a.active{background:var(--brand-soft);color:var(--brand);font-weight:600}
  nav.side .grp{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#94a3b8;margin:16px 10px 6px}
  main{padding:30px 0 90px;min-width:0}

  /* hero */
  .hero{background:linear-gradient(135deg,#3b5bdb,#0ea5e9);color:#fff;border-radius:var(--radius);
    padding:38px 34px;margin-bottom:10px;box-shadow:0 10px 30px rgba(59,91,219,.18)}
  .hero h1{margin:0 0 8px;font-size:30px;line-height:1.2}
  .hero p{margin:0;opacity:.96;font-size:17px;max-width:680px}
  .hero .cta{margin-top:18px;display:flex;gap:10px;flex-wrap:wrap}
  .hero .cta a{background:rgba(255,255,255,.16);color:#fff;border:1px solid rgba(255,255,255,.35);
    padding:9px 15px;border-radius:10px;font-weight:600;font-size:14px}
  .hero .cta a:hover{background:rgba(255,255,255,.26);text-decoration:none}

  section{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
    padding:26px 28px;margin:18px 0;scroll-margin-top:20px}
  section h2{margin:0 0 6px;font-size:22px}
  section h2 .sub{display:block;font-size:13px;font-weight:500;color:var(--muted);margin-top:2px}
  h3{margin:22px 0 8px;font-size:16px}
  p.lead{color:#445}
  .muted{color:var(--muted)}

  /* steps */
  .steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;margin-top:8px}
  .step{border:1px solid var(--line);border-radius:12px;padding:16px;background:#fbfcfe;position:relative}
  .step .n{width:28px;height:28px;border-radius:50%;background:var(--brand);color:#fff;display:grid;
    place-items:center;font-weight:700;font-size:14px;margin-bottom:8px}
  .step b{display:block;margin-bottom:3px}
  .step small{color:var(--muted)}

  /* glossary */
  .gloss{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
  .term{border:1px solid var(--line);border-radius:10px;padding:13px 15px;background:#fbfcfe}
  .term b{color:var(--brand)}

  /* cards / endpoints */
  .ep{border:1px solid var(--line);border-radius:12px;margin:12px 0;overflow:hidden}
  .ep>.head{display:flex;align-items:center;gap:12px;padding:13px 16px;cursor:pointer;background:#fbfcfe}
  .ep>.head:hover{background:#f3f5fb}
  .method{font-size:12px;font-weight:800;padding:3px 9px;border-radius:6px;color:#fff;letter-spacing:.03em}
  .m-get{background:var(--get)} .m-post{background:var(--post)} .m-put{background:var(--put)}
  .path{font-family:ui-monospace,monospace;font-weight:600;font-size:14px}
  .ep .summary{color:var(--muted);font-size:13px;margin-left:auto;text-align:right}
  .ep>.body{display:none;padding:6px 16px 18px;border-top:1px solid var(--line)}
  .ep.open>.body{display:block}
  .ep .chev{transition:transform .15s} .ep.open .chev{transform:rotate(90deg)}

  /* code */
  .codewrap{position:relative;margin:10px 0}
  pre{background:var(--code);color:var(--code-ink);padding:14px 15px;border-radius:10px;overflow:auto;
    font-size:13px;margin:0}
  .copy{position:absolute;top:8px;right:8px;background:#1e2a3f;color:#cbd5e1;border:1px solid #334155;
    border-radius:7px;font-size:12px;padding:4px 9px;cursor:pointer}
  .copy:hover{background:#293650}
  .tabs{display:flex;gap:6px;margin:10px 0 0}
  .tab{font-size:12px;padding:5px 11px;border:1px solid var(--line);border-radius:8px 8px 0 0;
    background:#f1f3f9;cursor:pointer;color:var(--muted)}
  .tab.active{background:var(--code);color:#fff;border-color:var(--code)}
  table{width:100%;border-collapse:collapse;font-size:13.5px;margin:10px 0}
  th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
  th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
  .pill{display:inline-block;background:var(--brand-soft);color:var(--brand);border-radius:20px;
    padding:1px 10px;font-size:12px;font-weight:600}
  .note{background:#fff7ed;border:1px solid #fed7aa;color:#9a3412;border-radius:10px;padding:12px 14px;margin:12px 0;font-size:14px}
  .ok{background:#ecfdf5;border:1px solid #a7f3d0;color:#065f46;border-radius:10px;padding:12px 14px;margin:12px 0;font-size:14px}
  .flow{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:13px;margin:8px 0}
  .flow span{background:#eef2ff;border:1px solid #c7d2fe;border-radius:20px;padding:3px 11px;color:#3730a3;font-weight:600}
  .flow .ar{color:#94a3b8}
  footer{color:var(--muted);font-size:13px;text-align:center;padding:30px 0 10px}
  @media(max-width:880px){.wrap{grid-template-columns:1fr}nav.side{display:none}}
</style>
</head>
<body>
<div class="wrap">
  <nav class="side">
    <div class="brand">📞 Call Review AI</div>
    <a href="#overview">Overview</a>
    <a href="#who">Who it's for</a>
    <a href="#how">How it works</a>
    <a href="#concepts">Key concepts</a>
    <div class="grp">API Reference</div>
    <a href="#ep-prompts">Prompts</a>
    <a href="#ep-process">Process calls</a>
    <a href="#ep-status">Status &amp; results</a>
    <a href="#ep-admin">Admin</a>
    <div class="grp">Guides</div>
    <a href="#walkthrough">Walkthrough</a>
    <a href="#dashboard">Dashboard</a>
    <a href="#faq">FAQ</a>
  </nav>

  <main>
    <div class="hero">
      <h1>Call Review AI</h1>
      <p>Turn raw call recordings into clean, English transcripts with speaker labels — and an automatic quality score against your own checklist. Built for sales &amp; support call QA.</p>
      <div class="cta">
        <a href="/docs">▶ Interactive API (try it live)</a>
        <a href="/admin">⚙ Admin dashboard</a>
        <a href="#walkthrough">📖 Quick start</a>
      </div>
    </div>

    <section id="overview">
      <h2>What is this? <span class="sub">In one paragraph</span></h2>
      <p class="lead">You give it a call recording (Hindi, Marathi, Hinglish, English…). It listens, writes out <b>who said what</b> (Agent vs Customer), translates everything to <b>English</b>, and then <b>scores the agent</b> against a checklist you define — returning a grade (A–F), per-point feedback, strengths, and improvements. Everything is available over a simple web API.</p>
      <div class="ok"><b>Plain-English version:</b> Upload a call → get back a readable transcript and a report card for the agent. No manual listening required.</div>
    </section>

    <section id="who">
      <h2>Who it's for <span class="sub">Typical users &amp; uses</span></h2>
      <table>
        <tr><th>User</th><th>What they use it for</th></tr>
        <tr><td>QA / Quality teams</td><td>Auto-score every call instead of sampling a few by hand</td></tr>
        <tr><td>Call-center managers</td><td>Spot coaching opportunities; track agent performance</td></tr>
        <tr><td>CRM / product teams</td><td>Attach transcripts &amp; scores to leads via the API + webhook</td></tr>
        <tr><td>Analysts</td><td>Multilingual calls turned into searchable English text</td></tr>
      </table>
    </section>

    <section id="how">
      <h2>How it works <span class="sub">Four steps</span></h2>
      <div class="steps">
        <div class="step"><div class="n">1</div><b>Create a scoring prompt</b><small>Upload a PDF/checklist of what a good call looks like. The AI turns it into a scoring rubric you can review &amp; edit.</small></div>
        <div class="step"><div class="n">2</div><b>Submit call recordings</b><small>Send one or many audio files (local path, web URL, or S3). Jobs run in the background.</small></div>
        <div class="step"><div class="n">3</div><b>AI processes each call</b><small>Transcribe → diarize (Agent/Customer) → translate to English → score against your rubric.</small></div>
        <div class="step"><div class="n">4</div><b>Get results</b><small>Poll for status, then read the transcript, the grade, per-criterion feedback, and token usage.</small></div>
      </div>
      <h3>Two AI engines (vendors)</h3>
      <table>
        <tr><th>Vendor</th><th>How it works</th><th>Best for</th></tr>
        <tr><td><span class="pill">gemini</span></td><td>One Google Gemini call does transcription + speaker labels + translation; a second cheap call scores it.</td><td>Multilingual calls, low cost, simplicity</td></tr>
        <tr><td><span class="pill">groq</span></td><td>PyAnnote (speaker split) + Whisper (transcription) + Groq LLM (scoring), run in parallel.</td><td>When you prefer the Whisper/PyAnnote stack</td></tr>
      </table>
    </section>

    <section id="concepts">
      <h2>Key concepts <span class="sub">Glossary — read this once</span></h2>
      <div class="gloss">
        <div class="term"><b>prompt</b><br>Your scoring checklist (a.k.a. rubric). Defines the criteria the agent is graded on. Has a stable <code>prompt_id</code>.</div>
        <div class="term"><b>audio_id</b><br>A unique name you give each call so you can look it up later. Must be unique.</div>
        <div class="term"><b>vendor</b><br>Which AI engine processes the call: <code>gemini</code> or <code>groq</code>.</div>
        <div class="term"><b>status / phase</b><br>Where a job is: <code>pending → downloading → processing_audio → processing_rating → completed</code> (or <code>failed</code>).</div>
        <div class="term"><b>transcript</b><br>The diarized English text: <code>AGENT: …</code> / <code>CUSTOMER: …</code>.</div>
        <div class="term"><b>rating_json</b><br>The scorecard: overall score (0–5), grade (A–F), per-criterion feedback, strengths, improvements.</div>
        <div class="term"><b>usage / tokens</b><br>How much AI work the call took (input/output tokens). Used for cost tracking.</div>
        <div class="term"><b>notify_url</b><br>Optional webhook — we POST to it when a job finishes, so you don't have to keep polling.</div>
      </div>
    </section>

    <!-- ===================== API REFERENCE ===================== -->
    <section id="ep-prompts">
      <h2>Prompts <span class="sub">Create &amp; manage scoring checklists</span></h2>
      <p class="muted">A prompt is created as a <b>draft</b>, you review/edit it, then mark it <b>verified</b> and reuse its <code>prompt_id</code> across many calls.</p>

      <div class="ep">
        <div class="head"><span class="method m-post">POST</span><span class="path">/prompts/from-file</span><span class="summary">PDF or rubric → AI-drafted prompt</span><span class="chev">▸</span></div>
        <div class="body">
          <p>Upload a <b>PDF</b> or a <b>.md/.txt</b> checklist. The AI reads it and drafts a structured scoring prompt. Saved with <code>status: "draft"</code>.</p>
          <p class="muted">Form fields: <code>service_name</code> (text), <code>file</code> (the upload).</p>
          <h3>Response</h3>
          <div class="codewrap"><button class="copy">Copy</button><pre>{
  "message": "Draft prompt generated. Review and verify with PUT /prompts/{prompt_id}.",
  "prompt_id": "a1b2c3d4-…",
  "service_name": "tvs_qa",
  "status": "draft",
  "source": "pdf",
  "prompt": "You are an AI call quality scorer…",
  "usage": { "input_tokens": 4120, "output_tokens": 760 }
}</pre></div>
        </div>
      </div>

      <div class="ep">
        <div class="head"><span class="method m-put">PUT</span><span class="path">/prompts/{prompt_id}</span><span class="summary">Edit &amp; approve in place</span><span class="chev">▸</span></div>
        <div class="body">
          <p>Edit the draft text and/or set <code>status: "verified"</code>. The <code>prompt_id</code> never changes, so anything already referencing it keeps working.</p>
          <h3>Request body</h3>
          <div class="codewrap"><button class="copy">Copy</button><pre>{
  "prompt": "…edited scoring rubric…",
  "status": "verified"
}</pre></div>
        </div>
      </div>

      <div class="ep">
        <div class="head"><span class="method m-post">POST</span><span class="path">/prompts/</span><span class="summary">Upload a .md prompt directly</span><span class="chev">▸</span></div>
        <div class="body">
          <p>Skip the AI drafting and store a Markdown prompt as-is. Form fields: <code>service_name</code>, <code>file</code> (.md). Returns a <code>prompt_id</code>.</p>
        </div>
      </div>

      <div class="ep">
        <div class="head"><span class="method m-get">GET</span><span class="path">/prompts/{prompt_id}</span><span class="summary">Read one prompt</span><span class="chev">▸</span></div>
        <div class="body"><p>Returns the prompt text, <code>service_name</code>, <code>status</code>, and <code>source</code>.</p></div>
      </div>

      <div class="ep">
        <div class="head"><span class="method m-get">GET</span><span class="path">/prompts/</span><span class="summary">List all prompts (paginated)</span><span class="chev">▸</span></div>
        <div class="body"><p>Lightweight list of saved prompts. Query params: <code>page</code>, <code>size</code>.</p></div>
      </div>
    </section>

    <section id="ep-process">
      <h2>Process calls <span class="sub">The main endpoint</span></h2>
      <div class="ep open">
        <div class="head"><span class="method m-post">POST</span><span class="path">/process-audio/</span><span class="summary">Submit one or many calls</span><span class="chev">▸</span></div>
        <div class="body">
          <p>Queue calls for transcription + scoring. Returns immediately with the <code>audio_id</code>s; the work runs in the background.</p>
          <table>
            <tr><th>Field</th><th>Required</th><th>Meaning</th></tr>
            <tr><td><code>prompt_id</code></td><td>yes</td><td>Which scoring checklist to grade against</td></tr>
            <tr><td><code>vendor</code></td><td>no</td><td><code>"gemini"</code> or <code>"groq"</code>. Defaults to the admin setting.</td></tr>
            <tr><td><code>gemini_model</code></td><td>no</td><td>Override the Gemini model for this request (e.g. <code>gemini-2.5-flash-lite</code>)</td></tr>
            <tr><td><code>audio_sources[]</code></td><td>yes</td><td>List of <code>{ audio_id, source }</code>. <code>source</code> = local path, http(s) URL, or <code>s3://</code> URI</td></tr>
            <tr><td><code>notify_url</code></td><td>no</td><td>Webhook called when each job finishes</td></tr>
          </table>
          <div class="tabs"><div class="tab active" data-tab="t-json">JSON body</div><div class="tab" data-tab="t-curl">curl</div></div>
          <div class="codewrap" id="t-json"><button class="copy">Copy</button><pre>{
  "vendor": "gemini",
  "gemini_model": "gemini-2.5-flash-lite",
  "prompt_id": "a1b2c3d4-…",
  "audio_sources": [
    { "audio_id": "call_001", "source": "https://example.com/call.wav" }
  ],
  "notify_url": null
}</pre></div>
          <div class="codewrap" id="t-curl" style="display:none"><button class="copy">Copy</button><pre>curl -X POST http://localhost:8000/process-audio/ \
  -H "Content-Type: application/json" \
  -d '{ "vendor":"gemini","prompt_id":"a1b2c3d4-…",
        "audio_sources":[{"audio_id":"call_001","source":"https://example.com/call.wav"}] }'</pre></div>
          <h3>Response</h3>
          <div class="codewrap"><button class="copy">Copy</button><pre>{
  "message": "Jobs queued. Poll GET /status/{audio_id} for progress.",
  "vendor": "gemini",
  "total_items": 1,
  "details": [ { "audio_id": "call_001", "phase": "pending" } ]
}</pre></div>
          <div class="note"><b>Note:</b> each <code>audio_id</code> must be unique — re-using one is skipped as a duplicate. The <code>source</code> must be reachable by the <i>server</i> (a public URL or a file on the server), not your laptop.</div>
        </div>
      </div>
    </section>

    <section id="ep-status">
      <h2>Status &amp; results <span class="sub">Get the transcript &amp; score</span></h2>
      <div class="flow"><span>pending</span><span class="ar">→</span><span>downloading</span><span class="ar">→</span><span>processing_audio</span><span class="ar">→</span><span>processing_rating</span><span class="ar">→</span><span>completed</span></div>
      <div class="ep open">
        <div class="head"><span class="method m-get">GET</span><span class="path">/status/{audio_id}</span><span class="summary">Poll a job</span><span class="chev">▸</span></div>
        <div class="body">
          <p>While running, returns the current <code>phase</code>. Once <code>completed</code>, returns the transcript, the scorecard, and token usage.</p>
          <h3>Completed response</h3>
          <div class="codewrap"><button class="copy">Copy</button><pre>{
  "audio_id": "call_001",
  "vendor": "gemini",
  "gemini_model": "gemini-2.5-flash-lite",
  "phase": "completed",
  "transcript": "AGENT: Good evening, this is Ramesh from TVS…\nCUSTOMER: Yes, tell me about the TVS King…",
  "rating_json": {
    "data": {
      "overall_score": 4, "grade": "B",
      "summary": "Qualified the lead well but missed the EMI explanation.",
      "criteria": [ { "name": "Greeting & intro", "score": 5, "feedback": "Clear and professional." } ],
      "strengths": ["Good rapport"], "improvements": ["Explain down payment"]
    }
  },
  "usage": { "tokens": { "input": 5200, "output": 640 } }
}</pre></div>
        </div>
      </div>
      <div class="ep">
        <div class="head"><span class="method m-get">GET</span><span class="path">/audio-ids/</span><span class="summary">List submitted calls</span><span class="chev">▸</span></div>
        <div class="body"><p>List of <code>audio_id</code>s with their status. Query params: <code>skip</code>, <code>limit</code>, <code>status</code>.</p></div>
      </div>
    </section>

    <section id="ep-admin">
      <h2>Admin <span class="sub">Protected — login from server config</span></h2>
      <p class="muted">All <code>/admin*</code> routes require a username/password (set on the server). Open <a href="/admin">/admin</a> for the visual dashboard.</p>
      <div class="ep">
        <div class="head"><span class="method m-get">GET</span><span class="path">/admin</span><span class="summary">Usage dashboard (HTML)</span><span class="chev">▸</span></div>
        <div class="body"><p>Totals: calls processed, completed/failed, call-minutes, tokens — plus model selection.</p></div>
      </div>
      <div class="ep">
        <div class="head"><span class="method m-get">GET</span><span class="path">/admin/models</span><span class="summary">Live model list</span><span class="chev">▸</span></div>
        <div class="body"><p>The models your API keys can actually use (powers the dropdowns).</p></div>
      </div>
      <div class="ep">
        <div class="head"><span class="method m-get">GET</span><span class="path">/admin/settings</span><span class="summary">Current vendor &amp; models</span><span class="chev">▸</span></div>
        <div class="body"><p>Returns the active vendor and the chosen model per vendor.</p></div>
      </div>
      <div class="ep">
        <div class="head"><span class="method m-post">POST</span><span class="path">/admin/settings</span><span class="summary">Change vendor/model</span><span class="chev">▸</span></div>
        <div class="body">
          <div class="codewrap"><button class="copy">Copy</button><pre>{ "active_vendor": "gemini", "gemini_model": "gemini-2.5-flash", "groq_model": "llama-3.3-70b-versatile" }</pre></div>
        </div>
      </div>
      <div class="ep">
        <div class="head"><span class="method m-get">GET</span><span class="path">/admin/dashboard</span><span class="summary">Usage metrics (JSON)</span><span class="chev">▸</span></div>
        <div class="body"><p>Aggregated jobs, models used, call-minutes, and token totals.</p></div>
      </div>
    </section>

    <!-- ===================== GUIDES ===================== -->
    <section id="walkthrough">
      <h2>Quick start <span class="sub">End-to-end in 4 calls</span></h2>
      <h3>1. Create &amp; verify a scoring prompt</h3>
      <div class="codewrap"><button class="copy">Copy</button><pre># upload your checklist (PDF or .md) → get a prompt_id
curl -X POST http://localhost:8000/prompts/from-file \
  -F "service_name=sales_qa" -F "file=@checklist.pdf"

# review it, then approve:
curl -X PUT http://localhost:8000/prompts/PROMPT_ID \
  -H "Content-Type: application/json" -d '{ "status":"verified" }'</pre></div>
      <h3>2. Submit a call</h3>
      <div class="codewrap"><button class="copy">Copy</button><pre>curl -X POST http://localhost:8000/process-audio/ \
  -H "Content-Type: application/json" \
  -d '{ "vendor":"gemini","prompt_id":"PROMPT_ID",
        "audio_sources":[{"audio_id":"call_001","source":"https://example.com/call.wav"}] }'</pre></div>
      <h3>3. Get the result</h3>
      <div class="codewrap"><button class="copy">Copy</button><pre>curl http://localhost:8000/status/call_001</pre></div>
      <div class="ok"><b>That's it.</b> You now have a diarized English transcript and a graded scorecard for the call.</div>
    </section>

    <section id="dashboard">
      <h2>Admin dashboard <span class="sub">No code required</span></h2>
      <p>Open <a href="/admin">/admin</a> and log in. You get:</p>
      <ul>
        <li><b>Usage at a glance</b> — total calls, completed/failed, call-minutes, tokens used.</li>
        <li><b>Model selection</b> — pick which AI model to use from a live list; click <b>Save</b>.</li>
        <li><b>Breakdown</b> — which vendors/models were used.</li>
      </ul>
      <p class="muted">For actual billing, check your AI provider's console — the dashboard tracks usage, not invoices.</p>
    </section>

    <section id="faq">
      <h2>FAQ &amp; troubleshooting</h2>
      <h3>What audio formats are supported?</h3>
      <p>WAV, MP3, M4A, OGG, FLAC, AAC, and more. The <code>source</code> can be a local path, a public <code>http(s)</code> URL, or an <code>s3://</code> URI.</p>
      <h3>What languages?</h3>
      <p>Hindi, Marathi, Hinglish, English and more — everything is translated to English in the transcript.</p>
      <h3>My job says <code>failed</code> — what now?</h3>
      <p>Read <code>error_detail</code> in the status. Common causes: the server can't reach the audio URL, or the file isn't valid audio. Re-submit with a new <code>audio_id</code> (failed ids can't be reused).</p>
      <h3>Why poll? Can I get notified instead?</h3>
      <p>Yes — pass a <code>notify_url</code> and we'll POST to it when each job finishes.</p>
      <h3>Where do I test requests live?</h3>
      <p>The interactive playground is at <a href="/docs">/docs</a> (Swagger) — fill in a request and hit <b>Execute</b>.</p>
    </section>

    <footer>Call Review AI · Interactive API: <a href="/docs">/docs</a> · Admin: <a href="/admin">/admin</a></footer>
  </main>
</div>

<script>
  // accordion
  document.querySelectorAll('.ep .head').forEach(h=>{
    h.addEventListener('click',()=>h.parentElement.classList.toggle('open'));
  });
  // copy buttons
  document.querySelectorAll('.copy').forEach(b=>{
    b.addEventListener('click',()=>{
      const pre=b.parentElement.querySelector('pre');
      navigator.clipboard.writeText(pre.innerText).then(()=>{
        const t=b.textContent; b.textContent='✓ Copied'; setTimeout(()=>b.textContent=t,1200);
      });
    });
  });
  // tabs (JSON / curl)
  document.querySelectorAll('.tab').forEach(t=>{
    t.addEventListener('click',()=>{
      const wrap=t.closest('.body');
      wrap.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
      t.classList.add('active');
      wrap.querySelector('#t-json').style.display = t.dataset.tab==='t-json'?'block':'none';
      wrap.querySelector('#t-curl').style.display = t.dataset.tab==='t-curl'?'block':'none';
    });
  });
  // active nav on scroll
  const links=[...document.querySelectorAll('nav.side a')];
  const map={}; links.forEach(a=>{const id=a.getAttribute('href').slice(1);const s=document.getElementById(id);if(s)map[id]=a;});
  const obs=new IntersectionObserver(es=>{
    es.forEach(e=>{ if(e.isIntersecting){ links.forEach(a=>a.classList.remove('active')); const a=map[e.target.id]; if(a)a.classList.add('active'); }});
  },{rootMargin:'-30% 0px -60% 0px'});
  Object.keys(map).forEach(id=>{const s=document.getElementById(id);if(s)obs.observe(s);});
</script>
</body>
</html>"""
