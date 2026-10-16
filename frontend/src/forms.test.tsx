// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot, Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Editor, SchemaFields } from "./components";
let host: HTMLDivElement, root: Root;
beforeEach(() => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});
it("leaves zero visible and shows optional values as empty inputs", () => {
  act(() =>
    root.render(
      <SchemaFields
        schema={{
          properties: { amount: { type: "number" }, notes: { type: "string" } },
        }}
        value={{ amount: 0, notes: null }}
        onChange={() => {}}
      />,
    ),
  );
  expect((host.querySelector("input") as HTMLInputElement).value).toBe("0");
  expect((host.querySelector("textarea") as HTMLTextAreaElement).value).toBe(
    "",
  );
});
it("shows errors without discarding the financial draft", async () => {
  const save = vi.fn().mockRejectedValue(Error("Revision veraltet."));
  act(() =>
    root.render(
      <Editor
        schema={{ properties: { amount: { type: "number" } } }}
        initial={{ amount: 123 }}
        onSave={save}
      />,
    ),
  );
  await act(async () => {
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  expect(host.textContent).toContain("Revision veraltet");
  expect((host.querySelector("input") as HTMLInputElement).value).toBe("123");
  expect(host.textContent).not.toContain("Gespeichert.");
});
it("uses a password input for credentials", () => {
  act(() =>
    root.render(
      <SchemaFields
        schema={{ properties: { key: { type: "string", format: "password" } } }}
        value={{ key: "" }}
        onChange={() => {}}
      />,
    ),
  );
  expect(host.querySelector("input")!.type).toBe("password");
});
