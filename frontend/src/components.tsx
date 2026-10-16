import React, { useEffect, useState } from "react";
import { api } from "./api";
export type Row = Record<string, any>;
export class ScreenBoundary extends React.Component<
  { children: React.ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <div className="notice error" role="alert">
        <p>
          Diese Ansicht konnte nicht dargestellt werden. Die gespeicherten Daten
          bleiben erhalten.
        </p>
        <button type="button" onClick={() => location.reload()}>
          Ansicht neu laden
        </button>
      </div>
    ) : (
      this.props.children
    );
  }
}
export const labels: Record<string, string> = {
  isin: "ISIN",
  name: "Name",
  security_name: "Wertpapier",
  security_type: "Wertpapierart",
  tax_class: "Steuerliche Einstufung",
  tax_class_source: "Quelle zur Einstufung",
  tax_class_verified: "Einstufung mit Quelle geprüft",
  fund_status: "Meldefondsstatus",
  fund_status_source: "Quelle zum Fondsstatus",
  fund_status_verified: "Fondsstatus mit Quelle geprüft",
  ticker: "Ticker",
  wkn: "WKN",
  country: "Sitzstaat (ISO-2)",
  currency: "Währung",
  notes: "Notiz",
  depot_id: "Depot",
  tx_type: "Buchungsart",
  trade_date: "Buchungsdatum",
  value_date: "Valuta",
  quantity: "Stückzahl",
  price: "Kurs",
  amount: "Bruttobetrag",
  fees: "Gebühren",
  fx_rate: "Währung je EUR",
  fx_source: "Kursquelle",
  withholding_tax: "Quellensteuer",
  withholding_country: "Quellenstaat (ISO-2)",
  kest_at_eur: "Österreichische KESt (EUR)",
  ratio: "Verhältnis neu / alt",
  income_category: "Ertragsart",
  income_category_verified: "Ertragsart mit Beleg geprüft",
  review_status: "Prüfstatus",
  execution_order: "Ausführungsreihenfolge",
  fund_name: "Fondsname",
  report_type: "Meldungsart",
  report_date: "Meldedatum",
  fiscal_year_end: "Geschäftsjahresende",
  distribution_date: "Ausschüttungsdatum",
  distribution_per_unit: "Ausschüttung / Anteil",
  age_per_unit: "AgE / Anteil",
  taxable_distribution_per_unit: "Steuerpflichtige Ausschüttung / Anteil",
  creditable_tax_per_unit: "Anrechenbare Steuer / Anteil",
  ak_correction_per_unit: "AK-Korrektur / Anteil",
  kest_per_unit: "KESt / Anteil",
  source: "Quelle",
  document_id: "Beleg-ID",
  is_meldefonds: "Meldefonds",
  broker_id: "Broker",
  account_ref: "Kontobezeichnung",
  active: "Aktiv",
  key: "Brokerart",
  tax_year: "Steuerjahr",
  first_price: "Erster Rücknahmepreis",
  last_price: "Letzter Rücknahmepreis",
  first_date: "Datum erster Preis",
  last_date: "Datum letzter Preis",
  fx_rate_last: "Währung je EUR zum Jahresende",
  doc_type: "Dokumentart",
  status: "Status",
  reason: "Begründung",
  price_symbol: "Kurssymbol",
  confirmed: "Alle Angaben mit dem Original abgeglichen",
  duplicate_confirmed: "Mögliche Dublette geprüft: eigenständiger Vorgang",
  kest_withheld: "Österreichische KESt vom Broker abgeführt",
  loss_offset_by_broker: "Verlustausgleich vom Broker durchgeführt",
  ocr_enabled: "Lokale OCR für gescannte Belege",
  auto_fetch: "Fehlende Devisenkurse automatisch von der EZB ergänzen",
  enabled: "KI-Vorschläge aktivieren",
  endpoint: "Basisadresse des eigenen KI-Servers",
  model: "Modellname",
  decision: "Entscheidung",
};
export const statusLabels: Record<string, string> = {
  ungeprueft: "Ungeprüft",
  pruefen: "Zu prüfen",
  geprueft: "Geprüft",
  verarbeitet: "Erledigt",
  neu: "Neu",
  teilweise: "Teilweise",
  fehlgeschlagen: "Nicht lesbar",
  ignoriert: "Ignoriert",
  berechnet: "Berechnet",
  vorlaeufig: "Vorläufig",
  manuell_pruefen: "Manuell prüfen",
  ja: "Ja",
  nein: "Nein",
  unbekannt: "Unbekannt",
  kein_fonds: "Kein Fonds",
  meldefonds: "Meldefonds",
  nichtmeldefonds: "Nichtmeldefonds",
  TradeRepublic: "Trade Republic",
  ScalableCapital: "Scalable Capital",
  Other: "Andere",
  beteiligung_kapitalgesellschaft: "Beteiligung an Kapitalgesellschaft",
  investmentfonds: "Investmentfonds",
  immobilienfonds: "Immobilienfonds – manuelle Prüfung",
  forderungswertpapier: "Forderungswertpapier / Anleihe",
  derivat_verbrieft_oeffentlich: "Verbrieftes öffentliches Derivat",
  derivat: "Derivat – manuelle Prüfung",
  sonstige: "Sonstige",
  ungeklaert: "Ungeklärt",
  auto: "Automatisch",
  dividende: "Dividende",
  sonstige_ausschuettung: "Sonstige Ausschüttung",
  kapitalrueckzahlung: "Kapitalrückzahlung",
  bestehend_behalten: "Bestehenden Wert behalten",
  verworfen: "Verworfen",
  neu_uebernommen: "Neuen Wert übernehmen",
  Unclassified: "Nicht erkannt",
};
export const display = (v: any) =>
  v == null
    ? "–"
    : typeof v === "boolean"
      ? v
        ? "Ja"
        : "Nein"
      : typeof v === "object"
        ? JSON.stringify(v)
        : statusLabels[String(v)] || String(v);
export const euro = (v: any) =>
  typeof v === "number"
    ? v.toLocaleString("de-AT", { style: "currency", currency: "EUR" })
    : "–";
export function ErrorBox({ error }: { error: unknown }) {
  return error ? (
    <div role="alert" className="notice error">
      {(error as Error).message || String(error)}
    </div>
  ) : null;
}
export function useResource<T = any>(path: string, revision = 0) {
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState<unknown>(null),
    [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api<T>(path, "GET", undefined, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setData(result);
      })
      .catch((e) => {
        if (!controller.signal.aborted && e.name !== "AbortError") setError(e);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, revision]);
  return { data, error, loading };
}
export function Loading() {
  return (
    <div className="loading" role="status">
      <span className="spinner" /> Daten werden geladen …
    </div>
  );
}
export function Badge({ value }: { value: any }) {
  return (
    <span
      className={
        "badge " +
        (["geprueft", "verarbeitet", "berechnet"].includes(value)
          ? "good"
          : value === "fehlgeschlagen"
            ? "bad"
            : "")
      }
    >
      {display(value)}
    </span>
  );
}
export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty">{children}</div>;
}
export function cellValue(key: string, value: any) {
  if (
    typeof value === "number" &&
    !["id", "tax_year", "year", "document_id"].includes(key)
  )
    return value.toLocaleString("de-AT", { maximumFractionDigits: 6 });
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value))
    return value.split("-").reverse().join(".");
  return display(value);
}
export function Table({
  rows,
  columns,
  onSelect,
  canSelect = () => true,
}: {
  rows: Row[];
  columns: [string, string][];
  onSelect?: (r: Row) => void;
  canSelect?: (r: Row) => boolean;
}) {
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(rows.length / 30));
  const safePage = Math.min(page, pages - 1);
  return (
    <>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {columns.map(([k, v]) => (
                <th key={k}>{v}</th>
              ))}
              {onSelect && (
                <th>
                  <span className="sr-only">Aktion</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {rows.slice(safePage * 30, safePage * 30 + 30).map((row, i) => (
              <tr key={row.id ?? i}>
                {columns.map(([k]) => (
                  <td
                    key={k}
                    className={
                      typeof row[k] === "number"
                        ? "cell-number"
                        : typeof row[k] === "string" &&
                            /^\d{4}-\d{2}-\d{2}$/.test(row[k])
                          ? "cell-date"
                          : [
                                "security_name",
                                "fund_name",
                                "depot_name",
                                "message",
                                "original_filename",
                                "notes",
                                "name",
                              ].includes(k)
                            ? "cell-text"
                            : undefined
                    }
                  >
                    {k === "review_status" || k === "status" ? (
                      <Badge value={row[k]} />
                    ) : (
                      cellValue(k, row[k])
                    )}
                  </td>
                ))}
                {onSelect && (
                  <td>
                    {canSelect(row) && (
                      <button
                        type="button"
                        className="small"
                        onClick={() => onSelect(row)}
                      >
                        Öffnen
                      </button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!rows.length && <Empty>Keine Einträge in dieser Ansicht.</Empty>}
      {pages > 1 && (
        <div className="pager">
          <button disabled={!safePage} onClick={() => setPage(safePage - 1)}>
            ← Zurück
          </button>
          <span>
            Seite {safePage + 1} von {pages} · {rows.length} Einträge
          </span>
          <button
            disabled={safePage === pages - 1}
            onClick={() => setPage(safePage + 1)}
          >
            Weiter →
          </button>
        </div>
      )}
    </>
  );
}
export function Pager({
  index,
  total,
  onChange,
  disabled = false,
}: {
  index: number;
  total: number;
  onChange: (i: number) => void;
  disabled?: boolean;
}) {
  return (
    <div className="pager">
      <button disabled={!index || disabled} onClick={() => onChange(index - 1)}>
        ← Zurück
      </button>
      <span>
        Eintrag {index + 1} von {total}
      </span>
      <button
        disabled={index >= total - 1 || disabled}
        onClick={() => onChange(index + 1)}
      >
        Weiter →
      </button>
    </div>
  );
}
export function SchemaFields({
  schema,
  value,
  onChange,
  keys,
  depots = [],
}: {
  schema: any;
  value: Row;
  onChange: (v: Row) => void;
  keys?: string[];
  depots?: Row[];
}) {
  const definitions = schema.$defs || {};
  return (
    <div className="form-grid">
      {(keys || Object.keys(schema.properties)).map((key) => {
        let prop = schema.properties[key];
        if (!prop) return null;
        let p = prop.anyOf?.find((p: any) => p.type !== "null") || prop;
        if (p.$ref) p = { ...definitions[p.$ref.split("/").pop()], ...p };
        const options =
          key === "depot_id"
            ? depots.map((d) => ({ value: d.id, label: d.name }))
            : p.enum?.map((v: any) => ({
                value: v,
                label: p.optionLabels?.[v] || display(v),
              }));
        const label = p.label || labels[key] || p.title || key;
        const v = value[key] ?? "";
        const set = (v: any) => onChange({ ...value, [key]: v });
        const required = schema.required?.includes(key);
        return (
          <label
            key={key}
            className={
              p.type === "boolean"
                ? "field-check wide"
                : key === "notes" ||
                    key.includes("source") ||
                    [
                      "tax_class",
                      "name",
                      "security_name",
                      "fund_name",
                    ].includes(key)
                  ? "wide"
                  : ""
            }
          >
            <span>
              {label}
              {required ? " *" : ""}
            </span>
            {options ? (
              <select
                aria-label={label}
                title={display(v)}
                value={v}
                required={required}
                onChange={(e) =>
                  set(
                    e.target.value === ""
                      ? null
                      : key === "depot_id" || p.type === "integer"
                        ? Number(e.target.value)
                        : e.target.value || null,
                  )
                }
              >
                <option value="">Bitte wählen</option>
                {options.map((o: any) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            ) : p.type === "boolean" ? (
              <input
                type="checkbox"
                aria-label={label}
                checked={Boolean(v)}
                onChange={(e) => set(e.target.checked)}
              />
            ) : key === "notes" ? (
              <textarea
                aria-label={label}
                value={v}
                rows={2}
                onChange={(e) => set(e.target.value || null)}
              />
            ) : (
              <input
                aria-label={label}
                value={v}
                type={
                  p.format === "password"
                    ? "password"
                    : p.format === "date"
                      ? "date"
                      : p.type === "number" || p.type === "integer"
                        ? "number"
                        : "text"
                }
                step={p.type === "integer" ? "1" : "any"}
                required={required}
                onChange={(e) =>
                  set(
                    e.target.value === ""
                      ? null
                      : p.type === "number" || p.type === "integer"
                        ? Number(e.target.value)
                        : e.target.value,
                  )
                }
              />
            )}
          </label>
        );
      })}
    </div>
  );
}
export function Editor({
  schema,
  initial,
  onSave,
  keys,
  depots,
  submit = "Speichern",
  children,
}: {
  schema: any;
  initial: Row;
  onSave: (v: Row) => Promise<void>;
  keys?: string[];
  depots?: Row[];
  submit?: string;
  children?: React.ReactNode;
}) {
  const [value, setValue] = useState(initial),
    [error, setError] = useState<unknown>(null),
    [busy, setBusy] = useState(false),
    [saved, setSaved] = useState(false),
    [baseline, setBaseline] = useState(JSON.stringify(initial));
  const dirty = JSON.stringify(value) !== baseline;
  useEffect(() => {
    const guard = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);
  return (
    <form
      data-dirty={dirty ? "true" : "false"}
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        setSaved(false);
        try {
          await onSave(value);
          setBaseline(JSON.stringify(value));
          setSaved(true);
        } catch (e) {
          setError(e);
        } finally {
          setBusy(false);
        }
      }}
    >
      <fieldset disabled={busy}>
        <SchemaFields
          schema={schema}
          value={value}
          onChange={(next) => {
            setValue(next);
            setSaved(false);
          }}
          keys={keys}
          depots={depots}
        />
        {children}
        <ErrorBox error={error} />
        {saved && (
          <div role="status" className="notice success">
            Gespeichert.
          </div>
        )}
        <div className="form-actions">
          <button className="primary" disabled={busy}>
            {busy ? "Wird gespeichert …" : submit}
          </button>
        </div>
      </fieldset>
    </form>
  );
}
export function Action({
  onClick,
  children,
  className = "",
  disabled = false,
}: {
  onClick: () => Promise<any>;
  children: React.ReactNode;
  className?: string;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null),
    [done, setDone] = useState("");
  return (
    <div className="action">
      <button
        type="button"
        className={className}
        disabled={busy || disabled}
        onClick={async () => {
          setBusy(true);
          setError(null);
          setDone("");
          try {
            const result = await onClick();
            if (result !== false)
              setDone(typeof result === "string" ? result : "Erledigt.");
          } catch (e) {
            setError(e);
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Bitte warten …" : children}
      </button>
      <ErrorBox error={error} />
      {done && (
        <span role="status" className="muted">
          {done}
        </span>
      )}
    </div>
  );
}
