import React, { useRef, useState } from "react";
import { api, BASE, editable } from "./api";
import {
  Action,
  Badge,
  Editor,
  Empty,
  ErrorBox,
  Loading,
  Row,
  Table,
  display,
  euro,
  useResource,
} from "./components";
import { Documents, choice, defaults, num, objectSchema, str } from "./review";

export function Dashboard({
  year,
  go,
}: {
  year: number;
  go: (p: string) => void;
}) {
  const { data, error, loading } = useResource("/dashboard?year=" + year);
  return (
    <>
      <div className="hero">
        <span className="eyebrow">DEINE STEUERN. DEIN ÜBERBLICK.</span>
        <h1>Alles bereit für den nächsten Schritt.</h1>
        <p>Belege sammeln, Angaben prüfen und Ergebnisse nachvollziehen.</p>
        <button className="primary" onClick={() => go("import")}>
          ＋ Dateien hinzufügen
        </button>
        <button onClick={() => go("dokumente")}>Offene Belege prüfen →</button>
      </div>
      <ErrorBox error={error} />
      {loading ? (
        <Loading />
      ) : (
        data && (
          <>
            <div className="stats">
              {[
                ["transactions", "Buchungen"],
                ["documents", "Belege im Jahr"],
                ["docs_to_review", "Offene Belege"],
                ["open_conflicts", "Datenkonflikte"],
              ].map(([key, label]) => (
                <div className="stat card" key={key}>
                  <span>{label}</span>
                  <strong>{data.stats[key]}</strong>
                </div>
              ))}
            </div>
            <div className="dashboard-grid">
              <div className="card">
                <div className="section-head">
                  <h2>Als Nächstes prüfen</h2>
                  <button className="text" onClick={() => go("dokumente")}>
                    Alle öffnen →
                  </button>
                </div>
                {data.pending.length ? (
                  data.pending.map((d: Row) => (
                    <button
                      className="task"
                      key={d.id}
                      onClick={() => go("dokumente")}
                    >
                      <span className="file-icon">▤</span>
                      <span>
                        <strong>{d.original_filename}</strong>
                        <small>{d.doc_type}</small>
                      </span>
                      <Badge value={d.status} />
                    </button>
                  ))
                ) : (
                  <Empty>Keine offenen Belege.</Empty>
                )}
              </div>
              <div className="card">
                <h2>Dein Ablauf</h2>
                {[
                  [
                    "01",
                    "import",
                    "Dateien hinzufügen",
                    "PDF, ZIP oder Tabelle hochladen.",
                  ],
                  [
                    "02",
                    "wertpapiere",
                    "Angaben vervollständigen",
                    "Original und erfasste Werte vergleichen.",
                  ],
                  [
                    "03",
                    "steuer",
                    "Steuerberechnung prüfen",
                    "Rechenweg und offene Fragen ansehen.",
                  ],
                  [
                    "04",
                    "exporte",
                    "Ergebnisse exportieren",
                    "Arbeitshilfe und Belege bereithalten.",
                  ],
                ].map(([n, p, t, s]) => (
                  <button className="step" key={n} onClick={() => go(p)}>
                    <b>{n}</b>
                    <span>
                      <strong>{t}</strong>
                      <small>{s}</small>
                    </span>
                    <span>→</span>
                  </button>
                ))}
              </div>
            </div>
            <details>
              <summary>Letzte Importe und Datenstatus</summary>
              <Table
                rows={data.recent_imports}
                columns={[
                  ["started_at", "Zeit"],
                  ["import_type", "Import"],
                  ["status", "Status"],
                  ["rows_imported", "Übernommen"],
                  ["rows_errors", "Offen"],
                ]}
              />
              <pre>{JSON.stringify(data.status, null, 2)}</pre>
            </details>
          </>
        )
      )}
    </>
  );
}

export function Upload({
  year,
  meta,
  changed,
}: {
  year: number;
  meta: Row;
  changed: () => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null),
    [result, setResult] = useState<Row | null>(null),
    [depot, setDepot] = useState(""),
    [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  async function upload(files: FileList | File[]) {
    if (busy || !files.length) return;
    setBusy(true);
    setError(null);
    setResult(null);
    const form = new FormData();
    Array.from(files).forEach((f) => form.append("files", f));
    form.append("year", String(year));
    if (depot) form.append("depot_id", depot);
    try {
      setResult(await api("/import", "POST", form));
      changed();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }
  return (
    <>
      <div
        className={"dropzone " + (drag ? "drag" : "")}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          void upload(e.dataTransfer.files);
        }}
      >
        <div className="upload-icon">⇧</div>
        <h2>
          {busy
            ? "Dateien werden importiert und geprüft …"
            : "Deine Belege hier ablegen"}
        </h2>
        <p>
          PDF, ZIP, CSV und Excel · Broker und Dokumentart werden automatisch
          erkannt.
        </p>
        <input
          className="sr-only"
          ref={input}
          type="file"
          multiple
          accept=".pdf,.zip,.csv,.txt,.xlsx"
          onChange={(e) => e.target.files && void upload(e.target.files)}
          aria-label="Dateien hochladen"
          disabled={busy}
        />
        <button
          className="primary"
          disabled={busy}
          onClick={() => input.current?.click()}
        >
          {busy ? "Import läuft …" : "Dateien auswählen"}
        </button>
        <small>
          Originale bleiben erhalten · Dubletten werden erkannt · maximal 50 MB
          pro Datei
        </small>
      </div>
      <ErrorBox error={error} />
      <details>
        <summary>Optionale Depotzuordnung</summary>
        <label>
          Falls nicht automatisch erkennbar
          <select value={depot} onChange={(e) => setDepot(e.target.value)}>
            <option value="">Automatisch zuordnen</option>
            {meta.depots.map((d: Row) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
      </details>
      {result && (
        <>
          <div className="notice success" role="status">
            Import abgeschlossen. {result.results.length} Dokumente geprüft;{" "}
            {result.upload.duplicates} Dubletten erkannt.
          </div>
          <Table
            rows={result.results}
            columns={[
              ["filename", "Datei"],
              ["status", "Ergebnis"],
              ["message", "Hinweis"],
            ]}
          />
          {result.upload.skipped?.length > 0 && (
            <div className="notice">
              Nicht übernommen:{" "}
              {result.upload.skipped
                .map((x: any) => (Array.isArray(x) ? x.join(": ") : display(x)))
                .join("; ")}
            </div>
          )}
          <Documents
            meta={meta}
            changed={changed}
            initialIds={result.results.map((r: Row) => r.document_id)}
          />
        </>
      )}
    </>
  );
}

export function Funds({
  year,
  meta,
  changed,
}: {
  year: number;
  meta: Row;
  changed: () => void;
}) {
  const [rev, setRev] = useState(0),
    [selected, setSelected] = useState<Row | null>(null);
  const refresh = () => {
    setRev((x) => x + 1);
    changed();
  };
  const funds = useResource<Row[]>("/funds", rev),
    conflicts = useResource<Row[]>("/conflicts", rev),
    prices = useResource<Row[]>("/nmf-prices?year=" + year, rev);
  const schema = {
    ...meta.schemas.fund,
    properties: {
      ...meta.schemas.fund.properties,
      review_status: choice(["ungeprueft", "geprueft", "verworfen"]),
      reason: str(),
    },
  };
  return (
    <>
      <div className="notice">
        OeKB-PDFs und Tabellen unter „Dateien hinzufügen“ hochladen. Abweichende
        Werte bleiben als Konflikt erhalten.
      </div>
      <ErrorBox error={funds.error} />
      <div className="card">
        <h2>Fondsmeldungen</h2>
        {funds.loading ? (
          <Loading />
        ) : (
          <Table
            rows={funds.data || []}
            columns={[
              ["report_date", "Meldedatum"],
              ["isin", "ISIN"],
              ["fund_name", "Fonds"],
              ["report_type", "Art"],
              ["age_per_unit", "AgE / Anteil"],
              ["review_status", "Prüfung"],
            ]}
            onSelect={setSelected}
          />
        )}
        <details open={!!selected} key={selected?.id || "new"}>
          <summary>
            {selected
              ? "Meldung #" + selected.id + " bearbeiten"
              : "Meldung manuell erfassen"}
          </summary>
          {selected && (
            <button onClick={() => setSelected(null)}>Neue Meldung</button>
          )}
          <Editor
            schema={schema}
            initial={selected || defaults(meta.schemas.fund)}
            onSave={async (v) => {
              if (selected)
                await api("/funds/" + selected.id, "PATCH", {
                  values: {
                    ...editable(meta.schemas.fund, v),
                    review_status: v.review_status || "ungeprueft",
                  },
                  reason: v.reason || "",
                });
              else await api("/funds", "POST", editable(meta.schemas.fund, v));
              setSelected(null);
              refresh();
            }}
          />
        </details>
      </div>
      <div className="card">
        <h2>Offene Konflikte</h2>
        <ErrorBox error={conflicts.error} />
        <Table
          rows={conflicts.data || []}
          columns={[
            ["id", "ID"],
            ["entity_key", "Zuordnung"],
            ["field", "Feld"],
            ["existing_value", "Bisher"],
            ["new_value", "Neu"],
          ]}
        />
        {(conflicts.data || []).map((c: Row) => (
          <details key={c.id}>
            <summary>
              {c.entity_key} · {c.field}
            </summary>
            <Editor
              schema={objectSchema(
                {
                  decision: choice(["bestehend_behalten", "neu_uebernommen"]),
                  reason: str(),
                },
                ["decision", "reason"],
              )}
              initial={{ decision: "bestehend_behalten", reason: "" }}
              onSave={async (v) => {
                if (c.entity === "nmf_price")
                  await api("/conflicts/" + c.id + "/nmf", "POST", {
                    values: { take_new: v.decision === "neu_uebernommen" },
                    reason: v.reason,
                  });
                else
                  await api("/conflicts/fund", "POST", {
                    existing_id: Number(c.existing_ref.match(/:(\d+)/)?.[1]),
                    new_id: Number(c.new_ref.match(/:(\d+)/)?.[1]),
                    decision: v.decision,
                    note: v.reason,
                  });
                refresh();
              }}
            />
          </details>
        ))}
      </div>
      <div className="card">
        <div className="section-head">
          <h2>Nichtmeldefonds-Kurse {year}</h2>
          <Action
            onClick={async () => {
              await api("/prices/" + year, "POST");
              refresh();
            }}
          >
            Kurse ergänzen
          </Action>
        </div>
        <ErrorBox error={prices.error} />
        <Table
          rows={prices.data || []}
          columns={[
            ["isin", "ISIN"],
            ["first_price", "Erster Preis"],
            ["last_price", "Letzter Preis"],
            ["currency", "Währung"],
            ["source", "Quelle"],
          ]}
        />
        <details>
          <summary>Rücknahmepreise manuell erfassen</summary>
          <Editor
            schema={objectSchema(
              {
                isin: str(),
                first_price: num,
                first_date: { format: "date", type: "string" },
                last_price: num,
                last_date: { format: "date", type: "string" },
                currency: str(),
                fx_rate_last: num,
                source: str(),
              },
              ["isin", "currency", "source"],
            )}
            initial={{ currency: "EUR" }}
            onSave={async (v) => {
              await api("/nmf-prices", "POST", { ...v, tax_year: year });
              refresh();
            }}
          />
        </details>
      </div>
    </>
  );
}

export function Brokers({
  meta,
  year,
  changed,
}: {
  meta: Row;
  year: number;
  changed: () => void;
}) {
  return (
    <>
      <div className="card">
        <h2>Broker</h2>
        <Table
          rows={meta.brokers}
          columns={[
            ["name", "Name"],
            ["key", "Brokerart"],
            ["country", "Land"],
          ]}
        />
        <details>
          <summary>Broker hinzufügen</summary>
          <Editor
            schema={objectSchema(
              {
                name: str(),
                key: choice(meta.broker_keys),
                country: str(),
                notes: str(),
              },
              ["name", "key"],
            )}
            initial={{ key: "Other" }}
            onSave={async (v) => {
              await api("/brokers", "POST", v);
              changed();
            }}
          />
        </details>
      </div>
      <div className="card">
        <h2>Depots und Steuerangaben {year}</h2>
        {meta.depots.map((d: Row) => (
          <DepotCard
            key={d.id + ":" + year}
            depot={d}
            year={year}
            changed={changed}
          />
        ))}
        <details>
          <summary>Depot hinzufügen</summary>
          <Editor
            schema={objectSchema(
              {
                broker_id: {
                  type: "integer",
                  enum: meta.brokers.map((b: Row) => b.id),
                },
                name: str(),
                account_ref: str(),
                currency: str(),
                notes: str(),
              },
              ["name", "broker_id"],
            )}
            initial={{ currency: "EUR" }}
            onSave={async (v) => {
              await api("/depots", "POST", {
                ...v,
                broker_id: Number(v.broker_id),
              });
              changed();
            }}
          />
        </details>
      </div>
    </>
  );
}
function DepotCard({
  depot,
  year,
  changed,
}: {
  depot: Row;
  year: number;
  changed: () => void;
}) {
  const { data, error } = useResource("/depots/" + depot.id + "/tax/" + year);
  return (
    <details>
      <summary>
        {depot.name} · {depot.broker_name} · {depot.currency}
      </summary>
      <ErrorBox error={error} />
      {data && (
        <Editor
          schema={objectSchema(
            {
              kest_withheld: choice(["ja", "nein", "unbekannt"]),
              loss_offset_by_broker: choice(["ja", "nein", "unbekannt"]),
              source: str(),
              notes: str(),
            },
            ["kest_withheld", "loss_offset_by_broker"],
          )}
          initial={data}
          onSave={async (v) => {
            await api("/depots/" + depot.id + "/tax/" + year, "PUT", {
              kest_withheld: v.kest_withheld,
              loss_offset_by_broker: v.loss_offset_by_broker,
              source: v.source || "",
              notes: v.notes || "",
            });
            changed();
          }}
        />
      )}
    </details>
  );
}

export function Tax({ year, go }: { year: number; go: (p: string) => void }) {
  const [rev, setRev] = useState(0),
    [tab, setTab] = useState("issues"),
    [line, setLine] = useState<Row | null>(null);
  const { data, error, loading } = useResource("/tax/" + year, rev);
  const tabs: Record<string, [string, string[]]> = {
    issues: ["Prüfhinweise", ["severity", "message", "ref", "action"]],
    lines: [
      "Rechenpositionen",
      ["date", "category", "name", "gross", "amount", "status"],
    ],
    e1kv: ["E 1kv-Arbeitshilfe", []],
    positions: ["Bestände", []],
    loss_offsets: ["Verlustausgleich", []],
    fund_rows: ["Fondsberechnung", []],
    nmf_rows: ["Nichtmeldefonds", []],
    rules_used: ["Regeln und Quellen", []],
    fees: ["Gebühren", []],
  };
  const rows = data?.[tab] || [];
  const columns = tabs[tab][1].length
    ? tabs[tab][1]
    : Object.keys(rows[0] || {});
  return (
    <>
      <div className="toolbar">
        <p>Arbeitshilfe · keine Übermittlung an FinanzOnline.</p>
        <button onClick={() => setRev((x) => x + 1)}>Neu berechnen</button>
      </div>
      <ErrorBox error={error} />
      {loading ? (
        <Loading />
      ) : (
        data && (
          <>
            <div className="card">
              <h2>Zusammenfassung {year}</h2>
              <p className="muted">
                Vorläufige und manuell zu prüfende Positionen bleiben
                ausdrücklich gekennzeichnet.
              </p>
              <div className="stats">
                {[
                  ["Geschätzte Steuer nach Anrechnung", "Steuerschätzung"],
                  ["Ungeklärte Beträge (nicht berechnet)", "Noch ungeklärt"],
                  ["Positionen gesamt", "Rechenpositionen"],
                  ["Positionen vorläufig", "Davon vorläufig"],
                ].map(([key, title]) => (
                  <div className="stat" key={key}>
                    <span>{title}</span>
                    <strong>
                      {key.startsWith("Positionen")
                        ? display(data.summary[key])
                        : euro(data.summary[key])}
                    </strong>
                  </div>
                ))}
              </div>
              <details>
                <summary>Alle Summen anzeigen</summary>
                <Table
                  rows={Object.entries(data.summary).map(([k, v]) => ({
                    key: k,
                    value:
                      typeof v === "number" && !k.startsWith("Positionen")
                        ? euro(v)
                        : v,
                  }))}
                  columns={[
                    ["key", "Position"],
                    ["value", "Wert"],
                  ]}
                />
                <details>
                  <summary>Nur bestätigte Positionen</summary>
                  <Table
                    rows={Object.entries(data.summary_confirmed).map(
                      ([k, v]) => ({ key: k, value: v }),
                    )}
                    columns={[
                      ["key", "Position"],
                      ["value", "Wert"],
                    ]}
                  />
                </details>
              </details>
            </div>
            <div className="tabs" role="tablist">
              {Object.entries(tabs).map(([key, [label]]) => (
                <button
                  role="tab"
                  aria-selected={tab === key}
                  className={tab === key ? "selected" : ""}
                  key={key}
                  onClick={() => setTab(key)}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="card">
              <Table
                rows={rows}
                columns={columns.map((k) => [
                  k,
                  (
                    {
                      severity: "Stufe",
                      message: "Hinweis",
                      ref: "Bezug",
                      action: "Nächster Schritt",
                      date: "Datum",
                      category: "Kategorie",
                      name: "Wertpapier",
                      gross: "Ausgangsbetrag EUR",
                      amount: "Steuerlicher Betrag EUR",
                      status: "Status",
                    } as Row
                  )[k] || k,
                ])}
                onSelect={
                  tab === "issues"
                    ? (r) => r.page && go(r.page)
                    : tab === "lines"
                      ? setLine
                      : undefined
                }
              />
            </div>
            {line && tab === "lines" && (
              <div className="card">
                <h2>{line.name || line.category} · Rechenweg</h2>
                <Badge value={line.status} />
                <ol>
                  {line.steps.map((step: string, i: number) => (
                    <li key={i}>{step}</li>
                  ))}
                </ol>
                <h3>Quellen und Regeln</h3>
                {line.sources.map((source: string, i: number) => (
                  <p key={i}>{source}</p>
                ))}
                <p>{line.rule_ids.join(", ")}</p>
                {line.notes.map((note: string, i: number) => (
                  <p className="check" key={i}>
                    {note}
                  </p>
                ))}
                {line.doc_ids.map((id: number) => (
                  <a
                    className="download"
                    href={BASE + "api/documents/" + id + "/original"}
                    target="_blank"
                    rel="noopener"
                    key={id}
                  >
                    Beleg #{id} öffnen ↗
                  </a>
                ))}
              </div>
            )}
          </>
        )
      )}
    </>
  );
}

export function Exports({ year }: { year: number }) {
  const [rev, setRev] = useState(0);
  const { data, error } = useResource<Row[]>("/exports?year=" + year, rev);
  return (
    <>
      <div className="card">
        <h2>Auswertung mit nachvollziehbarem Rechenweg</h2>
        <p>
          Vorläufige Werte und offene Prüfungen bleiben auch im Export
          gekennzeichnet.
        </p>
        <div className="toolbar">
          {[
            ["excel", "Excel"],
            ["csv", "CSV"],
            ["pdf", "PDF-Jahresbericht"],
            ["e1kv", "E 1kv-Arbeitshilfe"],
          ].map(([key, title]) => (
            <Action
              key={key}
              className="primary"
              onClick={async () => {
                await api("/exports/" + year + "/" + key, "POST");
                setRev((v) => v + 1);
              }}
            >
              {title} erstellen
            </Action>
          ))}
        </div>
      </div>
      <ErrorBox error={error} />
      <div className="card">
        <h2>Exporthistorie</h2>
        {(data || []).map((e) => (
          <a
            className="download"
            key={e.id}
            href={BASE + "api/exports/" + e.id + "/download"}
          >
            <span>
              <strong>{e.stored_path.split("/").pop()}</strong>
              <small>
                {e.ts} · {e.kind}
              </small>
            </span>
            <span>↓ Herunterladen</span>
          </a>
        ))}
        {!data?.length && <Empty>Noch keine Exporte für dieses Jahr.</Empty>}
      </div>
    </>
  );
}

export function Settings({ changed }: { changed: () => void }) {
  const [rev, setRev] = useState(0),
    [tab, setTab] = useState("recognition");
  const { data, error, loading } = useResource("/settings", rev);
  const audit = useResource("/audit", rev);
  const refresh = () => {
    setRev((r) => r + 1);
    changed();
  };
  return (
    <>
      <div className="tabs">
        {[
          ["recognition", "Dokumentenerkennung"],
          ["services", "Eigener KI-Server & Kurse"],
          ["audit", "Protokoll & Sicherung"],
        ].map(([k, t]) => (
          <button
            key={k}
            className={tab === k ? "selected" : ""}
            onClick={() => setTab(k)}
          >
            {t}
          </button>
        ))}
      </div>
      <ErrorBox error={error} />
      {loading ? (
        <Loading />
      ) : (
        data && (
          <div className="card">
            {tab === "recognition" ? (
              <>
                <h2>Dokumentenerkennung</h2>
                <Editor
                  schema={objectSchema({
                    ocr_enabled: { type: "boolean" },
                    auto_fetch: { type: "boolean" },
                  })}
                  initial={{
                    ocr_enabled: data.pdf.ocr_enabled,
                    auto_fetch: data.fx.auto_fetch,
                  }}
                  onSave={async (v) => {
                    await api("/settings", "PUT", {
                      values: {
                        pdf: { ...data.pdf, ocr_enabled: !!v.ocr_enabled },
                        fx: { auto_fetch: !!v.auto_fetch },
                      },
                    });
                    refresh();
                  }}
                />
              </>
            ) : tab === "services" ? (
              <>
                <h2>Vorhandenen KI-Server anbinden</h2>
                <p>
                  Ollama-kompatible Basisadresse und vorhandenes Modell. Der
                  Dienst erhält Belegtext erst nach deiner Bestätigung am
                  jeweiligen Beleg.
                </p>
                <Editor
                  schema={objectSchema(
                    {
                      enabled: { type: "boolean" },
                      endpoint: str(),
                      model: str(),
                    },
                    ["endpoint", "model"],
                  )}
                  initial={data.assistant}
                  onSave={async (v) => {
                    await api("/settings", "PUT", {
                      values: {
                        assistant: {
                          enabled: !!v.enabled,
                          endpoint: v.endpoint,
                          model: v.model,
                        },
                      },
                    });
                    refresh();
                  }}
                />
                <details>
                  <summary>Referenzdaten aus Dateien importieren</summary>
                  <ReferenceUpload kind="fx" changed={refresh} />
                  <ReferenceUpload kind="prices" changed={refresh} />
                </details>
                <h3>Kursdienst EODHD</h3>
                <p>
                  {data.eodhd_configured
                    ? "API-Schlüssel ist hinterlegt."
                    : "Kein API-Schlüssel hinterlegt."}
                </p>
                <Editor
                  schema={objectSchema({
                    key: { type: "string", format: "password" },
                  })}
                  initial={{ key: "" }}
                  submit="Schlüssel ersetzen"
                  onSave={async (v) => {
                    await api("/settings/eodhd", "PUT", {
                      values: { key: v.key || "" },
                    });
                    refresh();
                  }}
                />
              </>
            ) : (
              <>
                <h2>Sicherung und Änderungsprotokoll</h2>
                <Action
                  onClick={async () => {
                    const response = await fetch(BASE + "api/backup", {
                      method: "POST",
                      headers: { "X-KESt-Request": "1" },
                    });
                    if (!response.ok) throw Error("Sicherung fehlgeschlagen.");
                    const url = URL.createObjectURL(await response.blob());
                    const link = document.createElement("a");
                    link.href = url;
                    link.download = "KESt-Sicherung.zip";
                    link.click();
                    setTimeout(() => URL.revokeObjectURL(url), 1000);
                  }}
                >
                  Vollständige Sicherung herunterladen
                </Action>
                <p>
                  Enthält private Belege, Datenbank und Konfiguration. Sicher
                  aufbewahren.
                </p>
                <ErrorBox error={audit.error} />
                <Table
                  rows={audit.data?.audit || []}
                  columns={[
                    ["ts", "Zeit"],
                    ["entity", "Bereich"],
                    ["entity_id", "Eintrag"],
                    ["action", "Aktion"],
                    ["details", "Details"],
                  ]}
                />
                <RestoreBox changed={refresh} />
                <details>
                  <summary>Importprotokoll</summary>
                  <Table
                    rows={audit.data?.imports || []}
                    columns={[
                      ["id", "ID"],
                      ["started_at", "Zeit"],
                      ["status", "Status"],
                      ["rows_imported", "Übernommen"],
                      ["rows_errors", "Fehler"],
                    ]}
                  />
                </details>
              </>
            )}
          </div>
        )
      )}
    </>
  );
}

function ReferenceUpload({
  kind,
  changed,
}: {
  kind: string;
  changed: () => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null),
    [message, setMessage] = useState(""),
    [redemption, setRedemption] = useState(false);
  return (
    <div className="card">
      <h3>
        {kind === "fx"
          ? "EZB-Devisenkurse (CSV oder ZIP)"
          : "Wertpapierkurse (CSV)"}
      </h3>
      {kind === "prices" && (
        <label className="checkbox">
          <input
            type="checkbox"
            checked={redemption}
            onChange={(e) => setRedemption(e.target.checked)}
          />{" "}
          Datei enthält belegte Rücknahmepreise / NAV
        </label>
      )}
      <input
        aria-label={
          kind === "fx" ? "EZB-Datei importieren" : "Kursdatei importieren"
        }
        type="file"
        accept={kind === "fx" ? ".csv,.zip" : ".csv"}
        disabled={busy}
        onChange={async (e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          setBusy(true);
          setError(null);
          const form = new FormData();
          form.append("file", file);
          form.append("redemption", String(redemption));
          try {
            const result = await api("/reference-import/" + kind, "POST", form);
            setMessage(result.message);
            changed();
          } catch (e) {
            setError(e);
          } finally {
            setBusy(false);
          }
        }}
      />
      <ErrorBox error={error} />
      {message && <div className="notice success">{message}</div>}
    </div>
  );
}
function RestoreBox({ changed }: { changed: () => void }) {
  const [file, setFile] = useState<File | null>(null),
    [confirmed, setConfirmed] = useState(false);
  return (
    <details>
      <summary>Sicherung wiederherstellen</summary>
      <p>
        Die ausgewählte Sicherung wird geprüft. Vorhandene Daten werden zuvor
        gesichert und bleiben als Wiederherstellungsstand erhalten.
      </p>
      <input
        type="file"
        accept=".zip"
        aria-label="Sicherung auswählen"
        onChange={(e) => {
          setFile(e.target.files?.[0] || null);
          setConfirmed(false);
        }}
      />
      <label className="checkbox">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
        />{" "}
        Ich möchte diese Sicherung einspielen und den bisherigen Stand sichern
        lassen.
      </label>
      <Action
        onClick={async () => {
          if (!file || !confirmed)
            throw Error(
              "Sicherung auswählen und Wiederherstellung bestätigen.",
            );
          const form = new FormData();
          form.append("file", file);
          form.append("confirmed", "true");
          await api("/backup/restore", "POST", form);
          changed();
        }}
      >
        Bestätigte Sicherung einspielen
      </Action>
    </details>
  );
}
