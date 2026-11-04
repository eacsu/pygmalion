import { test, expect, type APIRequestContext } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

const element = JSON.parse(
  readFileSync(path.resolve("../../examples/circuits/rc-lowpass.json"), "utf8"),
);
async function mcp(
  request: APIRequestContext,
  name: string,
  args: object = {},
) {
  const response = await request.post("/mcp/", {
    headers: { Accept: "application/json, text/event-stream" },
    data: {
      jsonrpc: "2.0",
      id: 1,
      method: "tools/call",
      params: { name, arguments: args },
    },
  });
  expect(response.ok()).toBe(true);
  const result = (await response.json()).result;
  expect(result.isError, JSON.stringify(result)).toBeFalsy();
  return result.structuredContent;
}
async function create(request: APIRequestContext) {
  return mcp(request, "create_document", {
    document: {
      version: 3,
      name: "RC 低通 · 元件编辑",
      paper: "A4",
      margin_mm: 20,
      elements: [element],
    },
    idempotency_key: crypto.randomUUID(),
  });
}

test("MCP 电路可微调、撤销、保存、重新打开，元件移动保留引脚连接", async ({
  page,
  request,
}) => {
  const created = await create(request);
  let jobs = 0;
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/api/v1/jobs")) jobs++;
  });
  await page.goto("/?document=" + created.id);
  await expect(page.locator(".document-save-status")).toContainText(
    "已保存到服务端",
  );
  await page
    .getByRole("button", { name: "电路图：rc-lowpass", exact: true })
    .click();
  await page.getByRole("button", { name: "编辑电路", exact: true }).click();
  const resistor = page.getByRole("button", {
    name: "电路元件 R1",
    exact: true,
  });
  await expect(resistor).toBeVisible();
  await resistor.click();
  await page.getByLabel("元件参数", { exact: true }).fill("22kΩ");
  await page.getByLabel("元件参数", { exact: true }).press("Tab");
  await expect(page.locator(".document-save-status")).toContainText(
    "已保存到服务端",
  );
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(page.getByLabel("元件参数", { exact: true })).toHaveValue(
    "10kΩ",
  );
  await page.getByRole("button", { name: "重做", exact: true }).click();
  await expect(page.getByLabel("元件参数", { exact: true })).toHaveValue(
    "22kΩ",
  );
  await page.getByLabel("元件 X", { exact: true }).fill("42");
  await page.getByLabel("元件 X", { exact: true }).press("Enter");
  await expect(page.locator(".document-save-status")).toContainText(
    "已保存到服务端",
  );
  const updated = await mcp(request, "get_document", {
    document_id: created.id,
  });
  const circuit = updated.document.elements[0];
  expect(circuit.circuit.components[1].value).toBe("22kΩ");
  expect(circuit.circuit.components[1].x_mm).toBe(42);
  const render = await mcp(request, "render_circuit", { element: circuit });
  expect(render.layout.wires[0].points.at(-1)).toEqual(
    render.layout.components[1].pins.start,
  );
  await page.reload();
  await expect(
    page.getByRole("button", { name: "电路图：rc-lowpass", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "电路图：rc-lowpass", exact: true })
    .click();
  await page.getByRole("button", { name: "编辑电路", exact: true }).click();
  await page.getByLabel("选择电路元件").selectOption("r1");
  await expect(page.getByLabel("元件参数", { exact: true })).toHaveValue(
    "22kΩ",
  );
  await expect(page.getByLabel("元件 X", { exact: true })).toHaveValue("42");
  expect(jobs).toBe(0);
  await expect(page.locator(".circuit-loading")).toHaveCount(0);
  await expect(page.getByAltText("纸面真实笔画预览")).toBeVisible();
  await expect(page.locator(".inspector-preview")).toContainText(
    /预计用时|预览已最新/,
  );
  const hit = (await resistor.boundingBox())!;
  const mm = (await page.locator(".paper-element").boundingBox())!.width / 120;
  await page.mouse.move(hit.x + hit.width / 2, hit.y + hit.height / 2);
  await page.mouse.down();
  await page.mouse.move(
    hit.x + hit.width / 2 + 5 * mm,
    hit.y + hit.height / 2 + 4 * mm,
    { steps: 5 },
  );
  await page.mouse.up();
  await expect
    .poll(async () =>
      Number(await page.getByLabel("元件 X", { exact: true }).inputValue()),
    )
    .toBeCloseTo(47, 1);
  await expect
    .poll(async () =>
      Number(await page.getByLabel("元件 Y", { exact: true }).inputValue()),
    )
    .toBeCloseTo(24, 1);
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(page.getByLabel("元件 X", { exact: true })).toHaveValue("42");
  await expect(page.locator(".circuit-loading")).toHaveCount(0);
  await expect(page.locator(".inspector-preview")).toContainText(
    /预计用时|预览已最新/,
  );
  await Promise.all([
    page.waitForResponse(
      (r) => r.url().endsWith("/api/v1/circuits/layout") && r.ok(),
    ),
    page.getByRole("button", { name: "自动排版", exact: true }).click(),
  ]);
  await expect(page.locator(".document-save-status")).toContainText(
    "已保存到服务端",
  );
  const arranged = await mcp(request, "get_document", {
    document_id: created.id,
  });
  expect(
    arranged.document.elements[0].circuit.wires.map(
      (w: { start: object; end: object }) => [w.start, w.end],
    ),
  ).toEqual(
    circuit.circuit.wires.map((w: { start: object; end: object }) => [
      w.start,
      w.end,
    ]),
  );
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(page.getByLabel("元件 X", { exact: true })).toHaveValue("42");
  await page.screenshot({ path: "/tmp/pygmalion-circuit-editor.png" });
});

test("两点测距在缩放、平移后读数稳定，支持端点与 Shift，操作不写入文档", async ({
  page,
  request,
}) => {
  const created = await create(request);
  await page.goto("/?document=" + created.id);
  await expect(page.locator(".document-save-status")).toContainText(
    "已保存到服务端",
  );
  await expect(page.getByAltText("纸面真实笔画预览")).toBeVisible();
  await expect(page.locator(".paper-ruler,.ruler-corner")).toHaveCount(0);
  const zoom = page.getByLabel("纸面缩放", { exact: true });
  await zoom.selectOption("1");
  await page.getByRole("button", { name: "测量", exact: true }).click();
  const overlay = page.getByLabel("两点测量", { exact: true });
  const box = (await overlay.boundingBox())!;
  const x = box.x + 80,
    y = box.y + 100,
    scale = 96 / 25.4;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + 30 * scale, y + 40 * scale, { steps: 8 });
  await page.mouse.up();
  const reading = overlay.getByRole("status");
  await expect(reading).toContainText("50.00 mm");
  await expect(reading).toContainText("水平 30.00");
  await page.screenshot({ path: "/tmp/pygmalion-measurement.png" });
  await zoom.selectOption("2");
  await page.locator(".canvas-stage").evaluate((el) => {
    el.scrollLeft += 40;
    el.scrollTop += 30;
  });
  await expect(reading).toContainText("50.00 mm");
  await zoom.selectOption("1");
  const endpoint = page.getByRole("button", {
    name: "测量端点 2",
    exact: true,
  });
  await endpoint.focus();
  await page.keyboard.press("ArrowRight");
  await expect(reading).toContainText("水平 31.00");
  await page.keyboard.press("Escape");
  await expect(overlay).toHaveCount(0);
  await page.getByRole("button", { name: "测量", exact: true }).click();
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.keyboard.down("Shift");
  await page.mouse.move(x + 30 * scale, y + 40 * scale, { steps: 8 });
  await page.mouse.up();
  await page.keyboard.up("Shift");
  await expect(page.getByLabel("两点测量").getByRole("status")).toContainText(
    "水平 0.00",
  );
  await page.keyboard.press("h");
  await expect(page.getByLabel("两点测量")).toHaveCount(0);
  const current = await mcp(request, "get_document", {
    document_id: created.id,
  });
  expect(current.revision).toBe(created.revision);
  expect(current.document).toEqual(created.document);
});

test("待确认图片内容可定位并核对，暗色与窄屏可用", async ({
  page,
  request,
}) => {
  const draft = structuredClone(element);
  draft.circuit.uncertainties = [
    { target_id: "r1", message: "照片中的 R1 数值待核对" },
  ];
  const created = await mcp(request, "create_document", {
    document: {
      version: 3,
      name: "照片复刻草稿",
      paper: "A4",
      margin_mm: 20,
      elements: [draft],
    },
    idempotency_key: crypto.randomUUID(),
  });
  await page.goto("/?document=" + created.id);
  await page
    .getByRole("button", { name: "电路图：rc-lowpass", exact: true })
    .click();
  await expect(page.getByLabel("已核对：照片中的 R1 数值待核对")).toBeVisible();
  await page
    .getByRole("button", { name: "定位待确认项：照片中的 R1 数值待核对" })
    .click();
  await expect(page.getByLabel("选择电路元件")).toHaveValue("r1");
  await page.getByLabel("已核对：照片中的 R1 数值待核对").click();
  await expect(page.getByLabel("已核对：照片中的 R1 数值待核对")).toHaveCount(
    0,
  );
  await expect(page.locator(".document-save-status")).toContainText(
    "已保存到服务端",
  );
  await expect(
    page.getByRole("button", { name: "退出电路编辑", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "切换为夜间主题", exact: true })
    .click();
  await expect(page.locator(".circuit-loading")).toHaveCount(0);
  await expect(page.getByAltText("纸面真实笔画预览")).toBeVisible();
  await expect(page.locator(".inspector-preview")).toContainText(
    /预计用时|预览已最新/,
  );
  await page.screenshot({ path: "/tmp/pygmalion-circuit-night.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("button", { name: "测量", exact: true }),
  ).toBeVisible();
});
