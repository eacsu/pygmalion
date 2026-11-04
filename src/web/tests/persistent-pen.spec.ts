import { test, expect } from "@playwright/test";

test("笔头常驻，新文档左上角定位，旧文档只在编辑后绑定", async ({
  page,
  request,
}) => {
  const create = await request.post("/api/v1/documents", {
    headers: { "Idempotency-Key": crypto.randomUUID() },
    data: { version: 3, name: "未绑定旧文档", elements: [] },
  });
  const doc = await create.json();
  let motion = 0;
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      /\/jobs$|\/machine\/(commands|control-sessions)$/.test(r.url())
    )
      motion++;
  });
  await page.goto("/?document=" + doc.id);
  const marker = page.getByRole("button", { name: "笔头定位点", exact: true });
  await expect(marker).toBeVisible();
  await expect(
    page.getByRole("button", { name: "笔头定位", exact: true }),
  ).toHaveCount(0);
  await marker.click();
  await expect(page.getByLabel("笔头 X", { exact: true })).toHaveValue("0");
  expect(
    (await (await request.get("/api/v1/documents/" + doc.id)).json()).document
      .pen_anchor,
  ).toBeNull();
  await page.getByLabel("笔头 X", { exact: true }).fill("35");
  await page.getByLabel("笔头 X", { exact: true }).press("Enter");
  await expect(page.locator(".document-save-status")).toContainText(
    "已保存到服务端",
  );
  await page.getByRole("button", { name: "重置到左上角", exact: true }).click();
  await expect(marker).toBeVisible();
  await marker.click();
  await expect(page.getByLabel("笔头 X", { exact: true })).toHaveValue("0");
  await page.reload();
  await expect(marker).toBeVisible();
  await page.getByRole("button", { name: "新建", exact: true }).click();
  await expect(marker).toBeVisible();
  await marker.click();
  await expect(page.getByLabel("笔头 X", { exact: true })).toHaveValue("0");
  await expect(page.getByLabel("笔头 Y", { exact: true })).toHaveValue("0");
  await page.screenshot({ path: "/tmp/pygmalion-persistent-pen-fit.png" });
  expect(motion).toBe(0);
});

test("桌面工具区长坐标不产生横向溢出，缩放后的画布仍可滚动", async ({
  page,
}) => {
  await page.goto("/");
  const tools = page.getByRole("toolbar", { name: "纸面工具" });
  const value = page.locator(".paper-coordinate-value");
  await expect(value).toBeVisible();
  await value.evaluate((el) => {
    el.textContent = "-123456789.99, -123456789.99 mm";
  });
  const size = await tools.evaluate((el) => ({
    width: el.clientWidth,
    content: el.scrollWidth,
    overflow: getComputedStyle(el).overflowX,
  }));
  expect(size.content).toBeLessThanOrEqual(size.width);
  expect(size.overflow).toBe("hidden");
  await page.getByLabel("纸面缩放", { exact: true }).selectOption("4");
  expect(
    await page
      .locator(".canvas-stage")
      .evaluate((el) => el.scrollWidth > el.clientWidth),
  ).toBe(true);
  await page.screenshot({ path: "/tmp/pygmalion-persistent-pen-desktop.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("笔头移出画布视野时可找回，缩放和平移不会改变定位或提交运动", async ({
  page,
  request,
}) => {
  const created = await (
    await request.post("/api/v1/documents", {
      headers: { "Idempotency-Key": crypto.randomUUID() },
      data: {
        version: 3,
        name: "远处笔头",
        pen_anchor: { x_mm: -300, y_mm: 400 },
        elements: [],
      },
    })
  ).json();
  let motion = 0;
  page.on("request", (r) => {
    if (
      r.method() === "POST" &&
      /\/jobs$|\/machine\/(commands|control-sessions)$/.test(r.url())
    )
      motion++;
  });
  await page.goto("/?document=" + created.id);
  const locate = page.getByRole("button", {
    name: "显示笔头位置",
    exact: true,
  });
  const marker = page.getByRole("button", { name: "笔头定位点", exact: true });
  await expect(locate).toBeVisible();
  await locate.click();
  await expect(locate).toHaveCount(0);
  await expect(marker).toBeInViewport({ ratio: 1 });
  const viewport = (await page.locator(".paper-viewport").boundingBox())!;
  const pin = (await marker.boundingBox())!;
  expect(pin.x).toBeGreaterThan(viewport.x);
  expect(pin.x + pin.width).toBeLessThan(viewport.x + viewport.width);
  expect(pin.y).toBeGreaterThan(viewport.y);
  expect(pin.y + pin.height).toBeLessThan(viewport.y + viewport.height);
  await expect(marker).toBeFocused();
  await page.getByLabel("纸面缩放", { exact: true }).selectOption("4");
  await page.locator(".canvas-stage").evaluate((el) => {
    el.scrollLeft = 800;
    el.scrollTop = 900;
  });
  await expect(locate).toBeVisible();
  await locate.click();
  await expect(locate).toHaveCount(0);
  await expect(marker).toBeInViewport({ ratio: 1 });
  expect(
    (await (await request.get("/api/v1/documents/" + created.id)).json())
      .document.pen_anchor,
  ).toEqual({ x_mm: -300, y_mm: 400 });
  expect(
    (await (await request.get("/api/v1/documents/" + created.id)).json())
      .revision,
  ).toBe(created.revision);
  expect(motion).toBe(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(locate).toBeVisible();
  await locate.click();
  await expect(marker).toBeInViewport({ ratio: 1 });
  await marker.click({ trial: true });
  await page.getByRole("button", { name: "属性", exact: true }).click();
  await expect(locate).toContainText("笔头被面板遮住");
  await locate.click();
  await expect(locate).toHaveCount(0);
  await marker.click({ trial: true });
  await page.screenshot({ path: "/tmp/pygmalion-pen-revealed-mobile.png" });
});

test("夜间主题原点笔头在深色背景上清晰可见", async ({ page }) => {
  await page.goto("/");
  const marker = page.getByRole("button", { name: "笔头定位点", exact: true });
  await expect(marker).toBeInViewport({ ratio: 1 });
  await page
    .getByRole("button", { name: "切换为夜间主题", exact: true })
    .click();
  const textColor = await page
    .getByLabel("文档名称", { exact: true })
    .evaluate((el) => getComputedStyle(el).color);
  await expect(marker).toHaveCSS("color", textColor);
  await page.screenshot({ path: "/tmp/pygmalion-pen-origin-night.png" });
});
