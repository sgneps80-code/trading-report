"""
Sezione "Analisi tecnica per Claude" della pagina del report.

Inserita da generate_report.build_html. Tutto avviene nel browser:
- watchlist, posizioni e liquidita' restano nel localStorage del browser
  (mai nel repo pubblico), con esporta/importa JSON per spostarli tra PC;
- i pulsanti "Titolo" e "Portafoglio" avviano il workflow
  analisi_tecnica.yml con il token GitHub gia' salvato in "Sincronizza
  dati personali" (stesso meccanismo del resto della pagina);
- il workflow pubblica il file CIFRATO (AES-GCM, chiave derivata dalla
  password del sito) sul branch analisi-output; la pagina lo scarica,
  lo decifra e lo salva come .md nella cartella Download del browser.
"""

SHEETJS = "https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"

_HTML = r"""
  <!-- ANALISI TECNICA PER CLAUDE -->
  <div class="section" id="analisi-tecnica">
    <h2>🔬 Analisi tecnica per Claude <span class="badge-count">file .md da caricare in chat</span></h2>
    <p style="font-size:13px;color:#555;margin-bottom:12px">
      Watchlist e posizioni restano <b>solo in questo browser</b> (usa Esporta/Importa per portarle su un altro PC).
      Il file viene generato su GitHub Actions in 1-3 minuti, arriva cifrato e finisce nella cartella Download.
      Simboli in formato Yahoo: <code>ISP.MI</code>, <code>SAN.PA</code>, <code>SNY</code>, <code>EURUSD=X</code>, <code>GC=F</code>.
    </p>

    <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px">
      <input id="at-simbolo" type="text" placeholder="Simbolo (es. SAN.PA)" style="padding:8px;border:1px solid #ddd;border-radius:6px;font-size:14px;width:170px">
      <button class="at-btn" onclick="atTitolo(document.getElementById('at-simbolo').value)">📄 Titolo</button>
      <button class="at-btn" onclick="atPortafoglio()">📚 Portafoglio</button>
      <span style="flex:1"></span>
      <label style="font-size:12px;color:#555">Liquidità conto (EUR)
        <input id="at-liquidita" type="number" step="0.01" style="width:120px;padding:6px;border:1px solid #ddd;border-radius:6px" onchange="atSalva()"></label>
      <label style="font-size:12px;color:#555">ZigZag × ATR
        <input id="at-zz" type="number" step="0.1" min="0.5" value="1.5" style="width:60px;padding:6px;border:1px solid #ddd;border-radius:6px" onchange="atSalva()"></label>
    </div>
    <p id="at-status" style="font-size:13px;margin:8px 0;min-height:18px"></p>

    <div id="at-chiave" style="display:none;background:#fff7ed;border-radius:8px;padding:12px;margin-bottom:12px;font-size:13px">
      Per decifrare il file serve la password del sito (la stessa dell'accesso), solo la prima volta su questo browser:
      <input id="at-pwd" type="password" style="padding:6px;border:1px solid #ddd;border-radius:6px;margin-left:6px">
      <button class="at-btn" onclick="atChiaveDaCampo()">Conferma</button>
    </div>

    <div style="overflow-x:auto">
    <table id="at-tab" style="width:100%;border-collapse:collapse;font-size:12px;min-width:1200px">
      <thead><tr style="background:#1e3a5f;color:white">
        <th style="padding:6px">Simbolo</th><th>Nome</th><th>ISIN</th><th>Mercato</th><th>Valuta</th><th>Tipo</th>
        <th>Benchmark</th><th>Ticker TV</th><th title="es. SNY adr 0.5 EURUSD=X ; GC=F sottostante - EURUSD=X">Collegati ⓘ</th>
        <th>Quantità</th><th>Carico</th><th>Stop</th><th>Target</th><th>Uscita</th><th></th>
      </tr></thead>
      <tbody></tbody>
    </table>
    </div>

    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:10px">
      <button class="at-btn at-sec" onclick="atAggiungi()">＋ Aggiungi strumento</button>
      <button class="at-btn at-sec" onclick="atDaPosizioni()">⇩ Importa da "Le mie posizioni"</button>
      <label class="at-btn at-sec" style="cursor:pointer">⇩ Importa portafoglio-export.xls
        <input type="file" accept=".xls,.xlsx" style="display:none" onchange="atImportaXls(this)"></label>
      <button class="at-btn at-sec" onclick="atEsporta()">⇧ Esporta JSON</button>
      <label class="at-btn at-sec" style="cursor:pointer">⇩ Importa JSON
        <input type="file" accept=".json" style="display:none" onchange="atImportaJson(this)"></label>
    </div>
    <details style="margin-top:10px;font-size:12px;color:#555">
      <summary style="cursor:pointer">Come si compilano i campi</summary>
      <ul style="margin:8px 0 0 18px;line-height:1.6">
        <li><b>Tipo</b>: decide la compensabilità con lo zainetto (sì per azioni, ETC, obbligazioni, certificati; no per le plusvalenze degli ETF UCITS).
          Le righe importate dalle posizioni del report arrivano come "azione" o "etf": correggi gli ETC.</li>
        <li><b>Benchmark</b>: vuoto = FTSEMIB.MI per .MI, ^FCHI per .PA, ^GSPC per i titoli USA.</li>
        <li><b>Ticker TV</b>: facoltativo, per il controllo incrociato con lo screener (es. <code>MIL:ISP</code>, <code>EURONEXT:SAN</code>).</li>
        <li><b>Collegati</b>: <code>SIMBOLO tipo rapporto CAMBIO</code>, più voci separate da <code>;</code>.
          ADR: <code>SNY adr 0.5 EURUSD=X</code> (rapporto = azioni per 1 ADR: 2 ADR = 1 azione → 0.5).
          ETC: <code>GC=F sottostante - EURUSD=X</code> (il trattino = nessun rapporto).</li>
        <li><b>Uscita</b>: data pianificata AAAA-MM-GG.</li>
      </ul>
    </details>
  </div>
<style>
  .at-btn { background:#1e3a5f;color:white;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;font-size:14px;font-weight:600 }
  .at-btn:disabled { opacity:.5;cursor:wait }
  .at-sec { background:#e2e8f0;color:#1e3a5f;font-size:12px;padding:6px 12px }
  #at-tab td { padding:3px;border-bottom:1px solid #eee }
  #at-tab input, #at-tab select { width:100%;padding:4px;border:1px solid #ddd;border-radius:4px;font-size:12px;box-sizing:border-box }
</style>
<script>
(function () {
  const LS = "at_config_v1", LS_KEY = "tr_akey";
  const SALE = "trading-report/analisi-tecnica/v1", ITER = 310000;
  const CAMPI = ["simbolo","nome","isin","mercato","valuta","tipo","benchmark","tv","collegati","quantita","carico","stop","target","uscita"];
  const TIPI = ["","azione","etf","etc","obbligazione","certificato"];

  function leggi() {
    try { return JSON.parse(localStorage.getItem(LS)) || {strumenti: []}; } catch (e) { return {strumenti: []}; }
  }
  function scrivi(cfg) { try { localStorage.setItem(LS, JSON.stringify(cfg)); } catch (e) {} }
  function stato(msg, col) { const el = document.getElementById("at-status"); el.textContent = msg; el.style.color = col || "#333"; }
  function esc(s) { return String(s ?? "").replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;"); }

  // ─── collegati: "SNY adr 0.5 EURUSD=X ; GC=F sottostante - EURUSD=X" ↔ lista
  function collegatiDaTesto(t) {
    return String(t || "").split(";").map(x => x.trim()).filter(Boolean).map(x => {
      const [simbolo, tipo, rapporto, cambio] = x.split(/\s+/);
      const o = {simbolo: (simbolo || "").toUpperCase(), tipo: (tipo || "sottostante").toLowerCase()};
      if (rapporto && rapporto !== "-") o.rapporto = parseFloat(rapporto.replace(",", "."));
      if (cambio && cambio !== "-") o.cambio = cambio.toUpperCase();
      return o;
    });
  }
  function collegatiInTesto(l) {
    return (l || []).map(c => [c.simbolo, c.tipo || "sottostante", c.rapporto ?? "-", c.cambio || "-"].join(" ")).join(" ; ");
  }

  // ─── tabella ───────────────────────────────────────────────────────────────
  function riga(s) {
    const p = s.posizione || {};
    const v = {simbolo: s.simbolo, nome: s.nome, isin: s.isin, mercato: s.mercato, valuta: s.valuta, tipo: s.tipo,
               benchmark: s.benchmark, tv: s.tv, collegati: collegatiInTesto(s.collegati),
               quantita: p.quantita, carico: p.carico, stop: p.stop, target: p.target, uscita: p.uscita};
    const tr = document.createElement("tr");
    tr.innerHTML = CAMPI.map(c => {
      if (c === "tipo") return `<td><select data-c="tipo" onchange="atSalva()">${TIPI.map(t => `<option ${t === (v.tipo||"") ? "selected" : ""}>${t}</option>`).join("")}</select></td>`;
      const num = ["quantita","carico","stop","target"].includes(c);
      const w = c === "collegati" ? "min-width:180px" : (c === "nome" ? "min-width:120px" : "");
      return `<td><input data-c="${c}" ${num ? 'type="number" step="any"' : (c === "uscita" ? 'type="date"' : 'type="text"')} value="${esc(v[c])}" style="${w}" onchange="atSalva()"></td>`;
    }).join("") + `<td style="white-space:nowrap"><button class="at-btn at-sec" title="File Titolo" onclick="atTitolo(this.closest('tr').querySelector('[data-c=simbolo]').value)">📄</button>
      <button class="at-btn at-sec" title="Rimuovi" onclick="this.closest('tr').remove();atSalva()">✕</button></td>`;
    return tr;
  }
  function disegna(cfg) {
    const tb = document.querySelector("#at-tab tbody");
    tb.innerHTML = "";
    (cfg.strumenti || []).forEach(s => tb.appendChild(riga(s)));
    document.getElementById("at-liquidita").value = cfg.liquidita ?? "";
    document.getElementById("at-zz").value = cfg.zigzag_atr ?? 1.5;
  }
  function daTabella() {
    const strumenti = [];
    document.querySelectorAll("#at-tab tbody tr").forEach(tr => {
      const g = c => (tr.querySelector(`[data-c=${c}]`).value || "").trim();
      if (!g("simbolo")) return;
      const n = c => g(c) === "" ? null : parseFloat(g(c).replace(",", "."));
      const s = {simbolo: g("simbolo").toUpperCase(), nome: g("nome"), isin: g("isin").toUpperCase(), mercato: g("mercato"),
                 valuta: g("valuta").toUpperCase(), tipo: g("tipo"), benchmark: g("benchmark").toUpperCase(), tv: g("tv").toUpperCase(),
                 collegati: collegatiDaTesto(g("collegati"))};
      const pos = {quantita: n("quantita"), carico: n("carico"), stop: n("stop"), target: n("target"), uscita: g("uscita") || null};
      if (Object.values(pos).some(x => x !== null)) s.posizione = pos;
      strumenti.push(s);
    });
    const liq = document.getElementById("at-liquidita").value;
    return {versione: 1, strumenti, liquidita: liq === "" ? null : parseFloat(liq),
            zigzag_atr: parseFloat(document.getElementById("at-zz").value) || 1.5};
  }
  window.atSalva = function () { scrivi(daTabella()); };
  window.atAggiungi = function () { document.querySelector("#at-tab tbody").appendChild(riga({})); };

  function unisci(cfg, nuovi) {
    for (const n of nuovi) {
      const s = cfg.strumenti.find(x => (n.isin && x.isin === n.isin) || x.simbolo === n.simbolo);
      if (s) {
        for (const k of Object.keys(n)) if (k !== "posizione" && n[k] && !s[k]) s[k] = n[k];
        if (n.posizione) s.posizione = Object.assign({}, s.posizione || {}, Object.fromEntries(Object.entries(n.posizione).filter(([k, v]) => v !== null && v !== undefined)));
      } else cfg.strumenti.push(n);
    }
    return cfg;
  }

  // ─── import ────────────────────────────────────────────────────────────────
  function tvAYahoo(sym) {
    const [ex, t] = String(sym || "").includes(":") ? sym.split(":") : ["", sym];
    const suf = {MIL: ".MI", EURONEXT: ".PA", XETR: ".DE", LSE: ".L", SIX: ".SW", BME: ".MC"}[ex.toUpperCase()];
    return (t || "").toUpperCase() + (suf || "");
  }
  window.atDaPosizioni = function () {
    if (typeof REGOLE_ATTUALI === "undefined" || !REGOLE_ATTUALI.length) { stato("Nessuna posizione nel report", "#d97706"); return; }
    const nuovi = REGOLE_ATTUALI.map(r => ({
      simbolo: tvAYahoo(r.symbol), nome: r.name, isin: r.isin, tv: String(r.symbol || "").includes(":") ? r.symbol : "",
      tipo: (r.type || "").toLowerCase() === "azione" ? "azione" : "etf",
      posizione: {stop: r.stop, target: r.target}}));
    disegna(unisci(daTabella(), nuovi)); atSalva();
    stato(`Importate ${nuovi.length} posizioni (senza quantità/carico: usa l'import XLS). Verifica i simboli EURONEXT (.PA/.AS/.BR) e il tipo degli ETC.`, "#16a34a");
  };

  function caricaSheetJS() {
    return new Promise((ok, ko) => {
      if (window.XLSX) return ok();
      const s = document.createElement("script"); s.src = "__SHEETJS__"; s.onload = ok; s.onerror = () => ko(new Error("SheetJS non caricato"));
      document.head.appendChild(s);
    });
  }
  window.atImportaXls = async function (inp) {
    const f = inp.files[0]; if (!f) return;
    try {
      await caricaSheetJS();
      const wb = XLSX.read(await f.arrayBuffer(), {type: "array"});
      const righe = XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], {header: 1, raw: true, defval: ""});
      const norm = x => String(x).trim().toLowerCase().replace(/\s+/g, " ");
      const hi = righe.findIndex(r => r.map(norm).includes("isin") && r.map(norm).some(x => x.startsWith("quantit")));
      if (hi < 0) throw new Error("intestazione con ISIN e Quantità non trovata");
      const h = righe[hi].map(norm);
      const col = n => h.findIndex(x => x.startsWith(n));
      const ci = {titolo: col("titolo"), isin: col("isin"), simbolo: col("simbolo"), strumento: col("strumento"),
                  q: col("quantit"), car: col("p.zo medio di carico"), val: col("valuta"), merc: col("mercato")};
      const num = v => typeof v === "number" ? v : (String(v).includes(",") ? parseFloat(String(v).replace(/\./g, "").replace(",", ".")) : parseFloat(v));
      const tipo = s => { s = norm(s); return s.includes("etc") ? "etc" : s.includes("etf") ? "etf" : s.includes("obblig") ? "obbligazione"
                          : s.includes("certif") ? "certificato" : s.includes("azion") ? "azione" : ""; };
      const nuovi = [];
      for (const r of righe.slice(hi + 1)) {
        const isin = String(r[ci.isin] || "").trim().toUpperCase();
        if (!/^[A-Z]{2}[A-Z0-9]{10}$/.test(isin)) continue;
        nuovi.push({simbolo: String(ci.simbolo >= 0 ? r[ci.simbolo] : "").trim().toUpperCase(), nome: ci.titolo >= 0 ? String(r[ci.titolo]).trim() : "",
                    isin, tipo: ci.strumento >= 0 ? tipo(r[ci.strumento]) : "", valuta: ci.val >= 0 ? String(r[ci.val]).trim().toUpperCase() : "",
                    mercato: ci.merc >= 0 ? String(r[ci.merc]).trim() : "",
                    posizione: {quantita: num(r[ci.q]), carico: ci.car >= 0 ? num(r[ci.car]) : null}});
      }
      disegna(unisci(daTabella(), nuovi)); atSalva();
      stato(`Import XLS: ${nuovi.length} righe. Controlla che i simboli siano nel formato Yahoo (es. ISP.MI).`, "#16a34a");
    } catch (e) { stato("❌ Import XLS: " + e.message, "#dc2626"); }
    inp.value = "";
  };
  window.atEsporta = function () {
    const b = new Blob([JSON.stringify(daTabella(), null, 2)], {type: "application/json"});
    const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = "watchlist_analisi.json"; a.click();
  };
  window.atImportaJson = async function (inp) {
    try { const c = JSON.parse(await inp.files[0].text()); if (!Array.isArray(c.strumenti)) throw new Error("formato non valido");
          scrivi(c); disegna(c); stato(`Importati ${c.strumenti.length} strumenti`, "#16a34a"); }
    catch (e) { stato("❌ " + e.message, "#dc2626"); }
    inp.value = "";
  };

  // ─── chiave di decifratura (dalla password del sito) ─────────────────────
  async function derivaChiave(pwd) {
    const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(pwd), "PBKDF2", false, ["deriveBits"]);
    const bits = await crypto.subtle.deriveBits({name: "PBKDF2", hash: "SHA-256", salt: new TextEncoder().encode(SALE), iterations: ITER}, base, 256);
    return btoa(String.fromCharCode(...new Uint8Array(bits)));
  }
  window.analisiSalvaChiave = async function (pwd) {
    try { if (pwd) localStorage.setItem(LS_KEY, await derivaChiave(pwd)); } catch (e) {}
  };
  window.atChiaveDaCampo = async function () {
    const pwd = document.getElementById("at-pwd").value;
    if (typeof HASH !== "undefined" && HASH) {
      const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(pwd));
      const h = Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
      if (h !== HASH) { stato("❌ Password errata", "#dc2626"); return; }
    }
    await analisiSalvaChiave(pwd);
    document.getElementById("at-chiave").style.display = "none";
    stato("Chiave salvata in questo browser. Ripeti la richiesta.", "#16a34a");
  };
  async function decifra(blob) {
    const k = localStorage.getItem(LS_KEY);
    const raw = Uint8Array.from(atob(k), c => c.charCodeAt(0));
    const key = await crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["decrypt"]);
    const iv = Uint8Array.from(atob(blob.iv), c => c.charCodeAt(0));
    const ct = Uint8Array.from(atob(blob.ct), c => c.charCodeAt(0));
    const pt = await crypto.subtle.decrypt({name: "AES-GCM", iv}, key, ct);
    return JSON.parse(new TextDecoder().decode(pt));
  }

  // ─── richiesta al workflow e download ─────────────────────────────────────
  function gh() {
    const o = localStorage.getItem("gh_owner"), r = localStorage.getItem("gh_repo"), t = localStorage.getItem("gh_token");
    if (!o || !r || !t) throw new Error('Configura prima utente, repository e token in "Sincronizza dati personali" (in fondo alla pagina)');
    return {o, r, h: {"Authorization": `Bearer ${t}`, "Accept": "application/vnd.github+json"}};
  }
  const attesa = ms => new Promise(r => setTimeout(r, ms));
  let occupato = false;

  async function richiedi(modo, simbolo) {
    if (occupato) return;
    if (!localStorage.getItem(LS_KEY)) { document.getElementById("at-chiave").style.display = "block"; stato("Serve la password per decifrare", "#d97706"); return; }
    const cfg = daTabella(); scrivi(cfg);
    if (modo === "titolo" && !/^[A-Za-z0-9.\-\^=]{1,24}$/.test(simbolo || "")) { stato("Simbolo non valido", "#dc2626"); return; }
    if (modo === "portafoglio" && !cfg.strumenti.length) { stato("Watchlist vuota", "#dc2626"); return; }
    occupato = true;
    document.querySelectorAll("#analisi-tecnica .at-btn").forEach(b => b.disabled = true);
    try {
      const g = gh();
      const rid = Array.from(crypto.getRandomValues(new Uint8Array(12)), b => b.toString(16).padStart(2, "0")).join("");
      const inputs = {request_id: rid, modo, simbolo: modo === "titolo" ? simbolo.toUpperCase() : "", config_json: JSON.stringify(cfg)};
      const r = await fetch(`https://api.github.com/repos/${g.o}/${g.r}/actions/workflows/analisi_tecnica.yml/dispatches`,
                            {method: "POST", headers: {...g.h, "Content-Type": "application/json"}, body: JSON.stringify({ref: "main", inputs})});
      if (r.status !== 204) throw new Error(`avvio workflow: HTTP ${r.status} ${await r.text()}`);
      const t0 = Date.now();
      for (let k = 0; ; k++) {
        const sec = Math.round((Date.now() - t0) / 1000);
        stato(`⏳ Generazione in corso su GitHub Actions… ${sec}s (di solito 60-180s)`, "#d97706");
        if (sec > 600) throw new Error("nessun file dopo 10 minuti: controlla la scheda Actions del repository");
        await attesa(8000);
        const f = await fetch(`https://api.github.com/repos/${g.o}/${g.r}/contents/${rid}.json?ref=analisi-output&t=${Date.now()}`,
                              {headers: {...g.h, "Accept": "application/vnd.github.raw+json"}, cache: "no-store"});
        if (f.status === 200) {
          const doc = await decifra(await f.json());
          const a = document.createElement("a");
          a.href = URL.createObjectURL(new Blob([doc.md], {type: "text/markdown;charset=utf-8"}));
          a.download = doc.nome; document.body.appendChild(a); a.click(); a.remove();
          stato(`✅ Scaricato ${doc.nome} (${doc.md.length.toLocaleString("it-IT")} caratteri) nella cartella Download`, "#16a34a");
          return;
        }
        if (k % 3 === 2) {
          const rr = await fetch(`https://api.github.com/repos/${g.o}/${g.r}/actions/workflows/analisi_tecnica.yml/runs?per_page=15`, {headers: g.h, cache: "no-store"});
          if (rr.ok) {
            const run = ((await rr.json()).workflow_runs || []).find(x => x.display_title === `analisi ${rid}`);
            if (run && run.status === "completed" && run.conclusion !== "success")
              throw new Error(`il workflow è terminato con esito "${run.conclusion}": dettagli su ${run.html_url}`);
          }
        }
      }
    } catch (e) {
      stato("❌ " + (e.name === "OperationError" ? "decifratura fallita: la password salvata non corrisponde a SITE_PASSWORD (reinseriscila)" : e.message), "#dc2626");
      if (e.name === "OperationError") { localStorage.removeItem(LS_KEY); document.getElementById("at-chiave").style.display = "block"; }
    } finally {
      occupato = false;
      document.querySelectorAll("#analisi-tecnica .at-btn").forEach(b => b.disabled = false);
    }
  }
  window.atTitolo = s => richiedi("titolo", String(s || "").trim());
  window.atPortafoglio = () => richiedi("portafoglio", "");

  disegna(leggi());
})();
</script>
"""


def sezione_html() -> str:
    return _HTML.replace("__SHEETJS__", SHEETJS)
