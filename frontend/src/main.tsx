import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BASE } from "./api";
import { ErrorBox, Loading, Row, useResource } from "./components";
import { Documents, Securities, Transactions, mayNavigate } from "./review";
import {
  Brokers,
  Dashboard,
  Exports,
  Funds,
  Settings,
  Tax,
  Upload,
} from "./pages";
import "./style.css";

const nav = [
  ["", "Übersicht", "⌂"],
  ["import", "Dateien hinzufügen", "⇧"],
  ["dokumente", "Belege & Prüfung", "▤"],
  ["transaktionen", "Buchungen", "↔"],
  ["wertpapiere", "Wertpapiere", "◫"],
  ["fonds", "Fonds & OeKB", "▥"],
  ["depots", "Broker & Depots", "▣"],
  ["steuer", "Steuerberechnung", "∑"],
  ["exporte", "Exporte", "⇩"],
  ["einstellungen", "Einstellungen", "⚙"],
];
function readPage() {
  return location.pathname.replace(/^\/steuer\/?/, "").split("/")[0];
}
function App() {
  const [page, setPage] = useState(readPage),
    [revision, setRevision] = useState(0),
    [year, setYear] = useState<number | null>(null),
    [mobile, setMobile] = useState(false),
    [online, setOnline] = useState(navigator.onLine);
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem("kest-theme") || "system";
    } catch {
      return "system";
    }
  });
  const { data: meta, error, loading } = useResource<Row>("/meta", revision);
  useEffect(() => {
    const update = () => setPage(readPage());
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  useEffect(() => {
    const media = matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.theme =
        theme === "system" ? (media.matches ? "dark" : "light") : theme;
    };
    apply();
    media.addEventListener("change", apply);
    try {
      localStorage.setItem("kest-theme", theme);
    } catch {}
    return () => media.removeEventListener("change", apply);
  }, [theme]);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  useEffect(() => {
    if (meta && year === null)
      setYear(
        meta.years.includes(meta.default_year)
          ? meta.default_year
          : meta.years.at(-1),
      );
  }, [meta, year]);
  useEffect(() => {
    document.title =
      (nav.find((n) => n[0] === page)?.[1] || "KESt Manager") +
      " · KESt Manager";
  }, [page]);
  function go(p: string) {
    if (!mayNavigate()) return;
    history.pushState({}, "", BASE + p);
    setPage(p);
    setMobile(false);
    window.scrollTo(0, 0);
  }
  function changed() {
    setRevision((r) => r + 1);
  }
  const y = year || new Date().getFullYear() - 1;
  const screens: Record<string, React.ReactNode> = meta
    ? {
        "": <Dashboard key={y + ":" + revision} year={y} go={go} />,
        import: <Upload year={y} meta={meta} changed={changed} />,
        dokumente: <Documents meta={meta} changed={changed} />,
        transaktionen: <Transactions year={y} meta={meta} changed={changed} />,
        wertpapiere: <Securities meta={meta} changed={changed} />,
        fonds: <Funds year={y} meta={meta} changed={changed} />,
        depots: <Brokers meta={meta} year={y} changed={changed} />,
        steuer: <Tax key={y + ":" + revision} year={y} go={go} />,
        exporte: <Exports key={y} year={y} />,
        einstellungen: <Settings changed={changed} />,
      }
    : {};
  return (
    <>
      <a className="skip" href="#main">
        Zum Inhalt
      </a>
      <header className="topbar">
        <button
          className="menu-button"
          aria-label="Navigation öffnen"
          onClick={() => setMobile(!mobile)}
        >
          ☰
        </button>
        <a
          className="brand"
          href={BASE}
          onClick={(e) => {
            e.preventDefault();
            go("");
          }}
        >
          <span className="brand-mark">K</span>KESt <b>Manager</b>
        </a>
        <div className="top-actions">
          <span className="private-label">Private Steuerverwaltung</span>
          <select
            aria-label="Darstellung"
            value={theme}
            onChange={(e) => setTheme(e.target.value)}
          >
            <option value="system">◐ System</option>
            <option value="light">☀ Hell</option>
            <option value="dark">☾ Dunkel</option>
          </select>
          <span className="avatar">AT</span>
        </div>
      </header>
      <aside className={"sidebar " + (mobile ? "visible" : "")}>
        <label className="year">
          Steuerjahr
          <select
            aria-label="Steuerjahr"
            value={y}
            onChange={(e) => {
              if (mayNavigate()) setYear(Number(e.target.value));
            }}
          >
            {(meta?.years || [y]).map((v: number) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </label>
        <nav aria-label="Hauptnavigation">
          {nav.map(([p, label, icon], i) => (
            <React.Fragment key={p}>
              {[1, 4, 7, 9].includes(i) && (
                <div className="nav-section">
                  {
                    (
                      {
                        1: "Dateien & Prüfung",
                        4: "Stammdaten",
                        7: "Auswertung",
                        9: "System",
                      } as Record<number, string>
                    )[i]
                  }
                </div>
              )}
              <a
                href={BASE + p}
                aria-current={page === p ? "page" : undefined}
                className={page === p ? "active" : ""}
                onClick={(e) => {
                  e.preventDefault();
                  go(p);
                }}
              >
                <span className="nav-icon" aria-hidden>
                  {icon}
                </span>
                {label}
              </a>
            </React.Fragment>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="local-dot" /> Eigene Daten · Eigener Server
          <small>Version {meta?.version || "2.0.0"}</small>
        </div>
      </aside>
      {mobile && (
        <button
          className="scrim"
          aria-label="Navigation schließen"
          onClick={() => setMobile(false)}
        />
      )}
      <main id="main" className="workspace">
        <div className="breadcrumb">
          KESt Manager <span>/</span>{" "}
          {nav.find((n) => n[0] === page)?.[1] || "Seite nicht gefunden"}
        </div>
        {!online && (
          <div className="notice error">
            Offline. Finanzielle Änderungen benötigen eine Verbindung zum
            Server.
          </div>
        )}
        <ErrorBox error={error} />
        {!meta && loading ? (
          <Loading />
        ) : (
          <>
            {page !== "" && (
              <div className="page-title">
                <div>
                  <span className="eyebrow">STEUERJAHR {y}</span>
                  <h1>
                    {nav.find((n) => n[0] === page)?.[1] ||
                      "Seite nicht gefunden"}
                  </h1>
                </div>
              </div>
            )}
            {screens[page] || (
              <div className="empty">
                Diese Seite wurde nicht gefunden.{" "}
                <button onClick={() => go("")}>Zur Übersicht</button>
              </div>
            )}
          </>
        )}
        <footer>
          Arbeitshilfe für österreichische Kapitaleinkünfte · Keine Übermittlung
          an FinanzOnline.
        </footer>
      </main>
    </>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
if ("serviceWorker" in navigator)
  navigator.serviceWorker
    .register(BASE + "sw.js", { scope: BASE })
    .catch(() => {});
