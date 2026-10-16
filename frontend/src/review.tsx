import React, { useEffect, useState } from "react";
import { api, editable, original } from "./api";
import {
  Action,
  Badge,
  Editor,
  Empty,
  ErrorBox,
  Loading,
  Pager,
  Row,
  SchemaFields,
  Table,
  display,
  labels,
  useResource,
} from "./components";
export const fields = {
  transaction: [
    "depot_id",
    "tx_type",
    "trade_date",
    "value_date",
    "isin",
    "security_name",
    "quantity",
    "amount",
    "currency",
    "price",
    "fees",
    "fx_rate",
    "fx_source",
    "withholding_tax",
    "withholding_country",
    "kest_at_eur",
    "execution_order",
    "ratio",
    "income_category",
    "income_category_verified",
    "review_status",
    "notes",
  ],
  security: [
    "isin",
    "name",
    "security_type",
    "currency",
    "country",
    "ticker",
    "wkn",
    "tax_class",
    "tax_class_source",
    "tax_class_verified",
    "fund_status",
    "fund_status_source",
    "fund_status_verified",
    "notes",
  ],
};
export function defaults(schema: any) {
  return Object.fromEntries(
    Object.entries(schema.properties)
      .filter(([, v]: any) => v.default != null)
      .map(([k, v]: any) => [k, v.default]),
  );
}
export function objectSchema(properties: Row, required: string[] = []) {
  return { properties, required };
}
export const str = (title?: string) => ({ type: "string", title });
export const num = { type: "number" };
export const bool = { type: "boolean" };
export const choice = (values: any[]) => ({ type: "string", enum: values });
export function mayNavigate() {
  return (
    !document.querySelector('form[data-dirty="true"]') ||
    window.confirm("Ungespeicherte Eingaben verwerfen und weitergehen?")
  );
}
export function Evidence({ documents }: { documents: Row[] }) {
  const [index, setIndex] = useState(0);
  const doc = documents[Math.min(index, documents.length - 1)];
  if (!doc) return <Empty>Kein zugehöriger Originalbeleg vorhanden.</Empty>;
  return (
    <div className="original">
      <div className="section-head">
        <strong>{doc.original_filename}</strong>
        <a href={original(doc.id, true)}>Herunterladen</a>
      </div>
      {documents.length > 1 && (
        <label>
          Beleg
          <select
            value={index}
            onChange={(e) => setIndex(Number(e.target.value))}
          >
            {documents.map((d, i) => (
              <option value={i} key={d.id}>
                {d.original_filename}
              </option>
            ))}
          </select>
        </label>
      )}
      {doc.file_type === "pdf" ? (
        <iframe
          title={"Original: " + doc.original_filename}
          src={original(doc.id) + "#toolbar=1&navpanes=0"}
        />
      ) : (
        <TablePreview id={doc.id} />
      )}
    </div>
  );
}

export function Documents({
  meta,
  changed,
  initialIds,
}: {
  meta: Row;
  changed: () => void;
  initialIds?: number[];
}) {
  const focusId = Number(new URLSearchParams(location.search).get("beleg"));
  const [view, setView] = useState(focusId ? "all" : "open"),
    [q, setQ] = useState(""),
    [index, setIndex] = useState(0),
    [rev, setRev] = useState(0);
  const resource = useResource<Row[]>(
    "/documents?view=" + view + "&q=" + encodeURIComponent(q),
    rev,
  );
  const rows = (resource.data || []).filter(
    (d) => !initialIds || initialIds.includes(d.id),
  );
  const current = rows[Math.min(index, rows.length - 1)];
  const [focused, setFocused] = useState(false);
  useEffect(() => {
    if (!focused && resource.data) {
      const target = rows.findIndex((d) => d.id === focusId);
      if (target >= 0) setIndex(target);
      setFocused(true);
    }
  }, [resource.data, focused, focusId]);
  const refresh = () => {
    setRev((r) => r + 1);
    changed();
  };
  return (
    <>
      <div className="toolbar">
        <div className="segments">
          {[
            ["open", "Zu prüfen"],
            ["all", "Alle Belege"],
            ["done", "Erledigt"],
          ].map(([v, t]) => (
            <button
              className={view === v ? "selected" : ""}
              key={v}
              onClick={() => {
                if (mayNavigate()) {
                  setView(v);
                  setIndex(0);
                }
              }}
            >
              {t}
            </button>
          ))}
        </div>
        <input
          aria-label="Belege durchsuchen"
          placeholder="Dateiname, ISIN oder Notiz"
          value={q}
          onChange={(e) => {
            if (mayNavigate()) {
              setQ(e.target.value);
              setIndex(0);
            }
          }}
        />
        <Action
          disabled={resource.loading || !rows.length}
          onClick={async () => {
            if (!mayNavigate())
              throw Error(
                "Analyse abgebrochen. Ungespeicherte Eingaben bleiben erhalten.",
              );
            await api("/documents/process", "POST", {
              ids: rows.map((d) => d.id),
            });
            refresh();
          }}
        >
          Ansicht neu analysieren
        </Action>
      </div>
      <ErrorBox error={resource.error} />
      {resource.loading ? (
        <Loading />
      ) : !current ? (
        <Empty>
          Keine Belege in dieser Ansicht. Dateien unter „Dateien hinzufügen“
          importieren.
        </Empty>
      ) : (
        <>
          <Pager
            index={Math.min(index, rows.length - 1)}
            total={rows.length}
            onChange={(i) => {
              if (mayNavigate()) setIndex(i);
            }}
          />
          <DocumentCard
            key={current.id + ":" + rev}
            id={current.id}
            meta={meta}
            changed={refresh}
          />
        </>
      )}
      <details>
        <summary>Belegliste ({rows.length})</summary>
        <Table
          rows={rows}
          columns={[
            ["original_filename", "Datei"],
            ["source", "Quelle"],
            ["doc_type", "Dokumentart"],
            ["status", "Status"],
          ]}
          onSelect={(d) => {
            if (mayNavigate()) setIndex(rows.findIndex((x) => x.id === d.id));
          }}
        />
      </details>
    </>
  );
}
function DocumentCard({
  id,
  meta,
  changed,
}: {
  id: number;
  meta: Row;
  changed: () => void;
}) {
  const { data, error, loading } = useResource("/documents/" + id);
  const [ai, setAi] = useState<Row | null>(null),
    [selected, setSelected] = useState<string[]>([]),
    [consent, setConsent] = useState(false),
    [draft, setDraft] = useState<Row | null>(null);
  if (error) return <ErrorBox error={error} />;
  if (loading || !data) return <Loading />;
  const d = data.document,
    ex = data.extraction,
    linked = data.transactions[0];
  const initial = {
    ...defaults(meta.schemas.transaction),
    depot_id: data.suggested_depot,
    tx_type: ex.tx_type,
    ...Object.fromEntries(
      Object.entries(ex.fields || {}).map(([k, v]: any) => [k, v.value]),
    ),
    ...linked,
    ...draft,
  };
  const schema = {
    ...meta.schemas.transaction,
    properties: {
      ...meta.schemas.transaction.properties,
      reason: str(),
      confirmed: bool,
      duplicate_confirmed: bool,
    },
  };
  return (
    <>
      <div className="section-head">
        <div>
          <h2>{d.original_filename}</h2>
          <p>
            {d.doc_type} · {display(d.source)}
          </p>
        </div>
        <Badge value={d.status} />
      </div>
      <div className="review-grid">
        <Evidence documents={[d]} />
        <div className="card review-form">
          <h2>Direkt am Original prüfen</h2>
          {!ex.creates_transaction && (
            <div className="notice">
              Dieser Beleg ist keine bestätigte Einzelbuchung. Nur bei belegtem
              Vorgang eine Buchung anlegen; sonst den Belegstatus unten setzen.
            </div>
          )}
          {ex.checks
            ?.filter((c: Row) => ["warn", "error"].includes(c.result))
            .map((c: Row, i: number) => (
              <div key={i} className="check">
                <strong>{c.name}</strong>
                <span>{c.detail}</span>
                {c.action && <small>{c.action}</small>}
              </div>
            ))}
          {data.transactions.length > 1 && (
            <div className="notice">
              Mehrere Buchungen verknüpft. Jede Buchung unter „Buchungen“
              einzeln bearbeiten.
            </div>
          )}
          {d.doc_type === "OeKB-Fondsmeldung" ? (
            <FundDocumentEditor
              id={id}
              meta={meta}
              ex={ex}
              revision={data.revision}
              changed={changed}
            />
          ) : (
            <Editor
              key={String(id) + JSON.stringify(draft)}
              schema={schema}
              initial={initial}
              keys={[
                ...fields.transaction.filter((k) => k !== "review_status"),
                "reason",
                "confirmed",
                "duplicate_confirmed",
              ]}
              depots={meta.depots}
              submit={
                linked
                  ? "Geprüfte Änderung speichern"
                  : "Geprüfte Buchung anlegen"
              }
              onSave={async (v) => {
                await api("/documents/" + id + "/review", "POST", {
                  values: editable(meta.schemas.transaction, v),
                  reason: v.reason || "",
                  confirmed: !!v.confirmed,
                  duplicate_confirmed: !!v.duplicate_confirmed,
                  transaction_id: linked?.id || null,
                  revision: data.revision,
                });
                changed();
              }}
            />
          )}
          <details>
            <summary>Dokumentart und Belegstatus</summary>
            <Editor
              schema={objectSchema({
                doc_type: choice(meta.doc_types),
                status: choice(meta.doc_status),
                source: choice(meta.doc_sources),
                tax_year: { type: "integer" },
                notes: str(),
              })}
              initial={d}
              onSave={async (v) => {
                const values = Object.fromEntries(
                  ["doc_type", "status", "source", "tax_year", "notes"].map(
                    (k) => [k, v[k]],
                  ),
                );
                await api("/documents/" + id, "PATCH", {
                  values,
                  revision: data.revision,
                });
                changed();
              }}
            />
          </details>
          <details>
            <summary>Erkannte Werte und Textmuster</summary>
            <p>{ex.classification?.method}</p>
            {ex.classification?.evidence?.map((s: string, i: number) => (
              <blockquote key={i}>{s}</blockquote>
            ))}
            <Table
              rows={Object.entries(ex.fields || {}).map(([k, v]: any) => ({
                field: labels[k] || k,
                ...v,
              }))}
              columns={[
                ["field", "Feld"],
                ["value", "Erkannt"],
                ["source", "Textstelle"],
              ]}
            />
            {ex.components?.length > 0 && (
              <Table
                rows={ex.components}
                columns={Object.keys(ex.components[0]).map((k) => [k, k])}
              />
            )}
          </details>
          <details>
            <summary>KI-Vorschläge vom eigenen Server</summary>
            <p>
              Nur belegte Vorschläge ins Formular übernehmen. Vor dem Speichern
              am Original prüfen.
            </p>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
              />{" "}
              Belegtext an den eingerichteten KI-Server senden
            </label>
            <Action
              onClick={async () => {
                if (!consent)
                  throw Error(
                    "Bitte die Übermittlung dieses Belegtexts bestätigen.",
                  );
                setAi(
                  await api("/documents/" + id + "/assistant", "POST", {
                    confirmed: true,
                  }),
                );
              }}
            >
              Vorschläge ermitteln
            </Action>
            {ai && (
              <>
                {Object.entries(ai.fields || {}).map(([k, v]: any) => (
                  <label className="proposal" key={k}>
                    <input
                      type="checkbox"
                      checked={selected.includes(k)}
                      onChange={(e) =>
                        setSelected(
                          e.target.checked
                            ? [...selected, k]
                            : selected.filter((x) => x !== k),
                        )
                      }
                    />
                    <strong>
                      {labels[k] || k}: {display(v.value)}
                    </strong>
                    <small>{v.source}</small>
                  </label>
                ))}
                <button
                  disabled={!selected.length}
                  onClick={() => {
                    if (mayNavigate()) {
                      setDraft({
                        ...initial,
                        ...Object.fromEntries(
                          selected.map((k) => [k, ai.fields[k].value]),
                        ),
                        confirmed: false,
                      });
                    }
                  }}
                >
                  Ausgewählte Felder ins Formular übernehmen
                </button>
                {ai.rejected?.length > 0 && (
                  <p>Verworfen: {ai.rejected.join(", ")}</p>
                )}
              </>
            )}
          </details>
        </div>
      </div>
      <details>
        <summary>Belegprotokoll</summary>
        <Table
          rows={data.events}
          columns={[
            ["ts", "Zeit"],
            ["event", "Ereignis"],
            ["details", "Details"],
          ]}
        />
      </details>
    </>
  );
}

export function Securities({
  meta,
  changed,
}: {
  meta: Row;
  changed: () => void;
}) {
  const [q, setQ] = useState(""),
    [view, setView] = useState("open"),
    [index, setIndex] = useState(0),
    [rev, setRev] = useState(0);
  const { data, error, loading } = useResource<Row[]>(
    "/securities?q=" + encodeURIComponent(q),
    rev,
  );
  const rows = (data || []).filter(
    (s) =>
      view === "all" ||
      (view === "open" ? s.review_reasons.length : !s.review_reasons.length),
  );
  const cur = rows[Math.min(index, rows.length - 1)];
  const refresh = () => {
    setRev((r) => r + 1);
    changed();
  };
  return (
    <>
      <div className="toolbar">
        <div className="segments">
          {[
            ["open", "Offene Angaben"],
            ["done", "Geprüft"],
            ["all", "Alle Wertpapiere"],
          ].map(([v, t]) => (
            <button
              className={view === v ? "selected" : ""}
              key={v}
              onClick={() => {
                if (mayNavigate()) {
                  setView(v);
                  setIndex(0);
                }
              }}
            >
              {t}
            </button>
          ))}
        </div>
        <input
          placeholder="Name oder ISIN"
          aria-label="Wertpapiere durchsuchen"
          value={q}
          onChange={(e) => {
            if (mayNavigate()) {
              setQ(e.target.value);
              setIndex(0);
            }
          }}
        />
      </div>
      <ErrorBox error={error} />
      {loading ? (
        <Loading />
      ) : cur ? (
        <>
          <Pager
            index={Math.min(index, rows.length - 1)}
            total={rows.length}
            onChange={(i) => {
              if (mayNavigate()) setIndex(i);
            }}
          />
          <SecurityCard
            key={cur.isin + rev}
            isin={cur.isin}
            meta={meta}
            changed={refresh}
          />
        </>
      ) : (
        <Empty>Keine Wertpapiere in dieser Ansicht.</Empty>
      )}
      <details>
        <summary>Wertpapier anlegen</summary>
        <Editor
          schema={meta.schemas.security}
          initial={defaults(meta.schemas.security)}
          onSave={async (values) => {
            await api("/securities", "POST", { values });
            refresh();
          }}
        />
      </details>
    </>
  );
}
function SecurityCard({
  isin,
  meta,
  changed,
}: {
  isin: string;
  meta: Row;
  changed: () => void;
}) {
  const { data, error, loading } = useResource("/securities/" + isin);
  if (error) return <ErrorBox error={error} />;
  if (loading || !data) return <Loading />;
  const s = data.security;
  const schema = {
    ...meta.schemas.security,
    properties: {
      ...meta.schemas.security.properties,
      review_status: choice(["ungeprueft", "pruefen", "geprueft"]),
      price_symbol: str(),
    },
  };
  return (
    <>
      <div className="section-head">
        <div>
          <h2>{s.name || s.isin}</h2>
          <p>{s.isin}</p>
        </div>
        <Badge value={s.review_status} />
      </div>
      <div className="review-grid">
        <div>
          <div className="card">
            <h3>Offene Angaben und Quellen</h3>
            {data.review_reasons.length ? (
              data.review_reasons.map((r: string) => (
                <p className="check" key={r}>
                  {r}
                </p>
              ))
            ) : (
              <p>Alle erforderlichen Angaben sind geprüft.</p>
            )}
          </div>
          <Evidence documents={data.documents} />
        </div>
        <div className="card">
          <h2>Wertpapier bearbeiten</h2>
          <Editor
            schema={schema}
            initial={s}
            keys={[...fields.security, "review_status", "price_symbol"]}
            onSave={async (v) => {
              await api("/securities/" + isin, "PATCH", {
                values: editable(meta.schemas.security, v),
                review: v.review_status,
                price_symbol: v.price_symbol || "",
                revision: data.revision,
              });
              changed();
            }}
          />
        </div>
      </div>
    </>
  );
}

export function Transactions({
  year,
  meta,
  changed,
}: {
  year: number;
  meta: Row;
  changed: () => void;
}) {
  const [q, setQ] = useState(""),
    [selected, setSelected] = useState<number | null>(null),
    [rev, setRev] = useState(0),
    [status, setStatus] = useState("all");
  const { data, error, loading } = useResource<Row[]>(
    "/transactions?year=" + year,
    rev,
  );
  const refresh = () => {
    setRev((r) => r + 1);
    changed();
  };
  const rows = (data || []).filter(
    (r) =>
      (status === "all" || r.review_status === status) &&
      q
        .toLowerCase()
        .split(/\s+/)
        .every((w) =>
          [r.isin, r.security_name, r.depot_name, r.notes]
            .join(" ")
            .toLowerCase()
            .includes(w),
        ),
  );
  return (
    <>
      <div className="toolbar">
        <input
          placeholder="Name, ISIN, Depot oder Notiz"
          aria-label="Buchungen durchsuchen"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select
          aria-label="Prüfstatus"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          {["all", "ungeprueft", "pruefen", "geprueft"].map((v) => (
            <option key={v} value={v}>
              {v === "all" ? "Alle Prüfstatus" : display(v)}
            </option>
          ))}
        </select>
        <Action
          onClick={async () => {
            if (!mayNavigate()) return false;
            const results = await api("/fx/" + year, "POST");
            refresh();
            return results.length
              ? `${results.filter((r: Row) => r.status === "gesetzt").length} Devisenkurse ergänzt; ${results.filter((r: Row) => r.status !== "gesetzt").length} ohne verfügbaren Kurs.`
              : "Keine fehlenden Devisenkurse zu ergänzen.";
          }}
        >
          EZB-Kurse ergänzen
        </Action>
      </div>
      <ErrorBox error={error} />
      {loading ? (
        <Loading />
      ) : (
        <Table
          rows={[...rows].reverse()}
          columns={[
            ["trade_date", "Datum"],
            ["tx_type", "Art"],
            ["security_name", "Wertpapier"],
            ["amount", "Brutto"],
            ["currency", "Währung"],
            ["depot_name", "Depot"],
            ["review_status", "Prüfung"],
          ]}
          onSelect={(r) => {
            if (mayNavigate()) setSelected(r.id);
          }}
        />
      )}
      {selected && (
        <TransactionCard
          key={selected + ":" + rev}
          id={selected}
          meta={meta}
          changed={refresh}
          deleted={() => {
            setSelected(null);
            refresh();
          }}
        />
      )}
      <details>
        <summary>Buchung manuell hinzufügen</summary>
        <Editor
          key={year}
          schema={meta.schemas.transaction}
          keys={fields.transaction}
          initial={{
            ...defaults(meta.schemas.transaction),
            trade_date: `${year}-01-01`,
          }}
          depots={meta.depots}
          onSave={async (values) => {
            await api("/transactions", "POST", { values });
            refresh();
          }}
        />
      </details>
    </>
  );
}
function TransactionCard({
  id,
  meta,
  changed,
  deleted,
}: {
  id: number;
  meta: Row;
  changed: () => void;
  deleted: () => void;
}) {
  const { data, error, loading } = useResource("/transactions/" + id);
  if (error) return <ErrorBox error={error} />;
  if (loading || !data) return <Loading />;
  const schema = {
    ...meta.schemas.transaction,
    properties: { ...meta.schemas.transaction.properties, reason: str() },
  };
  return (
    <div className="review-grid">
      <Evidence documents={data.documents} />
      <div className="card">
        <h2>Buchung #{id} bearbeiten</h2>
        <Editor
          schema={schema}
          keys={[...fields.transaction, "reason"]}
          initial={data.transaction}
          depots={meta.depots}
          onSave={async (v) => {
            await api("/transactions/" + id, "PATCH", {
              values: Object.fromEntries(
                Object.entries(editable(meta.schemas.transaction, v)).filter(
                  ([k]) =>
                    !["document_id", "source_type", "source_ref"].includes(k),
                ),
              ),
              reason: v.reason || "",
              revision: data.revision,
            });
            changed();
          }}
        />
        <details>
          <summary>Buchung verwerfen</summary>
          <p>Die Buchung bleibt im Änderungsprotokoll erhalten.</p>
          <Editor
            schema={objectSchema({ reason: str() }, ["reason"])}
            initial={{ reason: "" }}
            submit="Buchung verwerfen"
            onSave={async (v) => {
              await api("/transactions/" + id, "DELETE", {
                values: {},
                reason: v.reason,
                revision: data.revision,
              });
              deleted();
            }}
          />
        </details>
      </div>
    </div>
  );
}

function TablePreview({ id }: { id: number }) {
  const { data, error, loading } = useResource<Row[]>(
    "/documents/" + id + "/preview",
  );
  return (
    <>
      <ErrorBox error={error} />
      {loading ? (
        <Loading />
      ) : (
        data?.map((table, i) => (
          <div key={i}>
            <small>
              Abschnitt {i + 1} · Vorschau von {Math.min(table.total, 300)} /{" "}
              {table.total} Zeilen
            </small>
            <Table
              rows={table.rows}
              columns={table.columns.map((k: string) => [k, k])}
            />
          </div>
        ))
      )}
    </>
  );
}
function FundDocumentEditor({
  id,
  meta,
  ex,
  revision,
  changed,
}: {
  id: number;
  meta: Row;
  ex: Row;
  revision: string;
  changed: () => void;
}) {
  const [index, setIndex] = useState(0);
  const candidates = ex.fund_reports || [];
  const candidate = candidates[index];
  const schema = {
    ...meta.schemas.fund,
    properties: { ...meta.schemas.fund.properties, confirmed: bool },
  };
  return (
    <>
      <h3>Fondsmeldung prüfen</h3>
      <p>
        Werte je Anteil aus der Privatanleger-Meldung. Keine zusätzliche
        Dividendenbuchung aus Summen anlegen.
      </p>
      {candidates.length > 1 && (
        <Pager
          index={index}
          total={candidates.length}
          onChange={(i) => {
            if (mayNavigate()) setIndex(i);
          }}
        />
      )}
      {candidate?.warnings?.map((w: string) => (
        <p className="check" key={w}>
          {w}
        </p>
      ))}
      <Editor
        key={index}
        schema={schema}
        initial={{
          ...defaults(meta.schemas.fund),
          ...candidate?.values,
          document_id: id,
          source: "OeKB / mit Original abgeglichen",
        }}
        onSave={async (v) => {
          await api("/documents/" + id + "/fund-review", "POST", {
            values: editable(meta.schemas.fund, v),
            confirmed: !!v.confirmed,
            revision,
          });
          changed();
        }}
      />
    </>
  );
}
