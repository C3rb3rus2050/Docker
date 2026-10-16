// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot, Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import {
  Action,
  SchemaFields,
  ScreenBoundary,
  Table,
  useResource,
} from "./components";
import { Dashboard, Exports, Funds, Settings, Tax } from "./pages";
import { Transactions } from "./review";
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: vi.fn(),
}));
let host: HTMLDivElement, root: Root;
const request = vi.mocked(api);
beforeEach(() => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  request.mockReset();
  vi.spyOn(window, "confirm").mockReturnValue(false);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
async function render(node: React.ReactNode) {
  await act(async () => {
    root.render(node);
  });
}
async function click(text: string) {
  const button = [...host.querySelectorAll("button")].find(
    (b) => b.textContent?.trim() === text,
  )!;
  expect(button, text).toBeTruthy();
  await act(async () => {
    button.click();
  });
}
async function change(label: string, value: string) {
  const input = host.querySelector(
    `[aria-label="${label}"]`,
  ) as HTMLInputElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
function submit(form: HTMLFormElement) {
  return act(async () => {
    form.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
  });
}
const schema = {
  properties: {
    isin: { type: "string" },
    report_date: { type: "string", format: "date" },
    currency: { type: "string" },
    age_per_unit: { type: "number" },
    document_id: { type: "integer" },
  },
};
it("ignores a superseded resource response even when the transport finishes after abort", async () => {
  const resolvers: ((v: any) => void)[] = [];
  request.mockImplementation(
    () => new Promise((resolve) => resolvers.push(resolve)),
  );
  function Probe({ path }: { path: string }) {
    const { data } = useResource(path);
    return <span>{JSON.stringify(data)}</span>;
  }
  await render(<Probe path="/old" />);
  await render(<Probe path="/new" />);
  await act(async () => resolvers[1](["current"]));
  await act(async () => resolvers[0]({ stale: true }));
  expect(host.textContent).toBe('["current"]');
});
it("allows every export action and preserves the download history after rapid refreshes", async () => {
  request.mockResolvedValue([
    { id: 1, stored_path: "exports/report.xlsx", ts: "2024", kind: "excel" },
  ]);
  await render(<Exports year={2024} />);
  for (const name of [
    "Excel erstellen",
    "CSV erstellen",
    "PDF-Jahresbericht erstellen",
    "E 1kv-Arbeitshilfe erstellen",
  ])
    await click(name);
  expect(
    request.mock.calls
      .filter(([, method]) => method === "POST")
      .map(([path]) => path),
  ).toEqual([
    "/exports/2024/excel",
    "/exports/2024/csv",
    "/exports/2024/pdf",
    "/exports/2024/e1kv",
  ]);
  expect(
    host.querySelector('a[href="/steuer/api/exports/1/download"]'),
  ).toBeTruthy();
});
it("submits only editable fund fields and the correction reason", async () => {
  request.mockImplementation(async (path, method) =>
    method === "PATCH"
      ? { ok: true }
      : path === "/funds"
        ? [
            {
              id: 1,
              active: 1,
              isin: "IE00B4L5Y983",
              report_date: "2024-01-01",
              currency: "EUR",
              age_per_unit: 1,
              document_id: 2,
            },
          ]
        : [],
  );
  await render(
    <Funds
      year={2024}
      meta={{ schemas: { fund: schema } }}
      changed={() => {}}
    />,
  );
  await click("Öffnen");
  await change("AgE / Anteil", "2");
  await change("Begründung", "Original geprüft");
  await submit(host.querySelector("form")!);
  const call = request.mock.calls.find(([, method]) => method === "PATCH")!;
  expect(call[0]).toBe("/funds/1");
  expect((call[2] as any).values.age_per_unit).toBe(2);
  expect((call[2] as any).values).not.toHaveProperty("isin");
  expect((call[2] as any).values).not.toHaveProperty("report_date");
  expect((call[2] as any).reason).toBe("Original geprüft");
});
it("closes a discarded booking instead of displaying a deleted record", async () => {
  let deleted = false;
  const transaction = { id: 1, trade_date: "2024-01-01", amount: 10 };
  request.mockImplementation(async (path, method) => {
    if (method === "DELETE") {
      deleted = true;
      return { ok: true };
    }
    return path === "/transactions/1"
      ? { transaction, documents: [], revision: "current" }
      : deleted
        ? []
        : [transaction];
  });
  await render(
    <Transactions
      year={2024}
      meta={{
        schemas: {
          transaction: { properties: { amount: { type: "number" } } },
        },
        depots: [],
      }}
      changed={() => {}}
    />,
  );
  await click("Öffnen");
  const discard = host.querySelector("details form")! as HTMLFormElement;
  const input = discard.querySelector("input")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "Musterfehler");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await submit(discard);
  expect(deleted).toBe(true);
  expect(host.textContent).not.toContain("Buchung #1 bearbeiten");
});
it("protects drafts when changing settings tabs and labels the API key correctly", async () => {
  request.mockImplementation(async (path) =>
    path === "/settings"
      ? {
          pdf: { ocr_enabled: false },
          fx: { auto_fetch: false },
          assistant: {
            enabled: false,
            endpoint: "http://ollama:11434",
            model: "test",
          },
        }
      : {},
  );
  await render(<Settings changed={() => {}} />);
  await act(async () =>
    (host.querySelector('input[type="checkbox"]') as HTMLInputElement).click(),
  );
  await click("Eigener KI-Server & Kurse");
  expect(window.confirm).toHaveBeenCalled();
  expect(host.textContent).toContain("Lokale OCR");
  expect(host.textContent).not.toContain("API-Schlüssel");
  vi.mocked(window.confirm).mockReturnValue(true);
  await click("Eigener KI-Server & Kurse");
  expect(
    host.querySelector(
      'input[aria-label="EODHD-API-Schlüssel"][type="password"]',
    ),
  ).toBeTruthy();
});
it("does not offer inert Open buttons for informational tax notices", async () => {
  request.mockResolvedValue({
    summary: {},
    summary_confirmed: {},
    issues: [
      { message: "Information", page: "" },
      { message: "Prüfen", page: "wertpapiere" },
    ],
  });
  const go = vi.fn();
  await render(<Tax year={2024} go={go} />);
  expect(
    [...host.querySelectorAll("button")].filter(
      (b) => b.textContent === "Öffnen",
    ),
  ).toHaveLength(1);
  await click("Öffnen");
  expect(go).toHaveBeenCalledWith("wertpapiere");
});
it("opens the exact pending document selected on the dashboard", async () => {
  request.mockResolvedValue({
    stats: {},
    pending: [{ id: 42, original_filename: "MUSTER.pdf" }],
    recent_imports: [],
    status: {},
  });
  const go = vi.fn();
  await render(<Dashboard year={2024} go={go} />);
  await act(async () =>
    host.querySelector<HTMLButtonElement>("button.task")!.click(),
  );
  expect(go).toHaveBeenCalledWith("dokumente?beleg=42");
});
it("keeps an empty numeric selection empty instead of silently changing it to zero", async () => {
  const changed = vi.fn();
  await render(
    <SchemaFields
      schema={{ properties: { broker_id: { type: "integer", enum: [1] } } }}
      value={{ broker_id: 1 }}
      onChange={changed}
    />,
  );
  await act(async () => {
    const select = host.querySelector("select")!;
    select.value = "";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(changed).toHaveBeenCalledWith({ broker_id: null });
});
it("disables unavailable actions and shows returned results", async () => {
  const action = vi.fn().mockResolvedValue("Keine fehlenden Kurse.");
  await render(
    <Action disabled onClick={action}>
      Prüfen
    </Action>,
  );
  await click("Prüfen");
  expect(action).not.toHaveBeenCalled();
  await render(<Action onClick={action}>Prüfen</Action>);
  await click("Prüfen");
  expect(host.textContent).toContain("Keine fehlenden Kurse.");
});
it("keeps table paging within the available records", async () => {
  const rows = Array.from({ length: 61 }, (_, i) => ({
    id: i + 1,
    name: `MUSTER ${i + 1}`,
  }));
  await render(<Table rows={rows} columns={[["name", "Name"]]} />);
  await click("Weiter →");
  await click("Weiter →");
  expect(host.textContent).toContain("Seite 3 von 3");
  expect(host.textContent).toContain("MUSTER 61");
  await render(<Table rows={rows.slice(0, 1)} columns={[["name", "Name"]]} />);
  expect(host.textContent).toContain("MUSTER 1");
  expect(host.textContent).not.toContain("MUSTER 61");
});
it("keeps a recoverable error screen instead of blanking the application", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  function Broken(): React.ReactNode {
    throw Error("synthetic render error");
  }
  await render(
    <ScreenBoundary>
      <Broken />
    </ScreenBoundary>,
  );
  expect(host.querySelector('[role="alert"]')).toBeTruthy();
  expect(host.textContent).toContain("gespeicherten Daten bleiben erhalten");
  expect(host.querySelector("button")!.textContent).toBe("Ansicht neu laden");
});
