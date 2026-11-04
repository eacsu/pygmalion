import { test, expect } from "@playwright/test";

async function visibleInk(page: import("@playwright/test").Page) {
  const paper = (await page.locator(".canvas-paper").boundingBox())!;
  const scale = paper.width / 210;
  const screenshot = await page.screenshot({
    clip: {
      x: paper.x + 19 * scale,
      y: paper.y + 19 * scale,
      width: 30 * scale,
      height: 14 * scale,
    },
  });
  return page.evaluate(async (png) => {
    const image = new Image();
    image.src = `data:image/png;base64,${png}`;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = image.width;
    canvas.height = image.height;
    const context = canvas.getContext("2d")!;
    context.drawImage(image, 0, 0);
    const pixels = context.getImageData(0, 0, image.width, image.height).data;
    let ink = 0;
    for (let i = 0; i < pixels.length; i += 4) {
      if (pixels[i] < 150 && pixels[i + 1] < 150 && pixels[i + 2] < 150) ink++;
    }
    return ink;
  }, screenshot.toString("base64"));
}

async function resetDefaults(
  request: import("@playwright/test").APIRequestContext,
) {
  const current = await (await request.get("/api/v1/settings/editor")).json();
  expect(
    (
      await request.patch("/api/v1/settings/editor", {
        data: { font_size_mm: 8 },
        headers: { "If-Match": current.etag },
      })
    ).ok(),
  ).toBe(true);
}
test.beforeEach(async ({ request }) => resetDefaults(request));
test.afterEach(async ({ request }) => resetDefaults(request));

test("v1：默认字号、独立文本框与笔头定位在刷新和撤销后保持一致", async ({
  page,
}) => {
  await page.goto("/");
  const defaults = page.getByLabel("默认字号", { exact: true });
  await defaults.fill("6");
  await page.getByRole("button", { name: "保存默认字号", exact: true }).click();
  await expect(page.locator(".editor-defaults summary")).toContainText("6 mm");
  await page.getByRole("button", { name: "添加文本框", exact: true }).click();
  const editor = page.getByLabel("文本框内容", { exact: true });
  await editor.fill("甲乙");
  await editor.press("Escape");
  const size = page.getByLabel("字号", { exact: true });
  await expect(size).toHaveValue("6");
  await size.fill("10");
  await size.press("Tab");
  await page.getByRole("button", { name: "添加文本框", exact: true }).click();
  await editor.fill("丙");
  await editor.press("Escape");
  await expect(size).toHaveValue("6");
  const stored = () =>
    page.evaluate(() =>
      JSON.parse(localStorage.getItem("pygmalion-document-v2")!),
    );
  const before = (await stored()).elements;
  await page.getByRole("button", { name: "笔头定位点", exact: true }).click();
  const marker = page.getByRole("button", { name: "笔头定位点", exact: true });
  await expect(marker).toBeVisible();
  await page.getByLabel("笔头 X", { exact: true }).fill("35");
  await page.getByLabel("笔头 Y", { exact: true }).fill("45");
  await page.getByLabel("笔头 Y", { exact: true }).press("Tab");
  expect((await stored()).elements).toEqual(before);
  expect((await stored()).pen_anchor).toEqual({ x_mm: 35, y_mm: 45 });
  const bounds = await marker.boundingBox();
  const paper = await page.locator(".canvas-paper").boundingBox();
  const scale = paper!.width / 210;
  await page.mouse.move(bounds!.x + 16, bounds!.y + 16);
  await page.mouse.down();
  await page.mouse.move(
    bounds!.x + 16 + 10 * scale,
    bounds!.y + 16 + 5 * scale,
  );
  await page.mouse.up();
  expect((await stored()).pen_anchor.x_mm).toBeCloseTo(45, 1);
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  expect((await stored()).pen_anchor).toEqual({ x_mm: 35, y_mm: 45 });
  await page.reload();
  await expect(marker).toBeVisible();
  expect((await stored()).elements).toEqual(before);
  await marker.click();
  await expect(page.getByLabel("笔头 X", { exact: true })).toHaveValue("35");
  const preview = page.getByRole("img", {
    name: "纸面真实笔画预览",
    exact: true,
  });
  await expect(preview).toBeVisible();
  const previewUrl = await preview.getAttribute("src");
  await marker.press("ArrowRight");
  await expect(preview).toHaveAttribute("src", previewUrl!);
  expect((await stored()).pen_anchor.x_mm).toBe(36);
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  expect((await stored()).pen_anchor.x_mm).toBe(35);
  await expect(preview).toHaveAttribute("src", previewUrl!);
  await expect(
    page.getByRole("button", { name: "开始书写", exact: true }),
  ).toBeEnabled();
  const ink = await visibleInk(page);
  expect(ink).toBeGreaterThan(30);
  const themePreviewUrl = await preview.getAttribute("src");
  await page.screenshot({ path: test.info().outputPath("anchor-vallum.png") });
  await page
    .getByRole("button", { name: "切换为夜间主题", exact: true })
    .click();
  await expect(preview).toHaveAttribute("src", themePreviewUrl!);
  await preview.evaluate(async (img: HTMLImageElement) => {
    await img.decode();
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
    );
  });
  expect(await visibleInk(page)).toBeGreaterThan(ink * 0.9);
  await page.screenshot({ path: test.info().outputPath("anchor-abyssus.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(marker).toBeVisible();
  const properties = page.getByRole("button", { name: "属性", exact: true });
  if ((await properties.getAttribute("aria-expanded")) !== "true")
    await properties.click();
  await expect(page.getByLabel("笔头 X", { exact: true })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("anchor-narrow.png") });
  await properties.click();
  await expect(marker).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("anchor-narrow-canvas.png"),
  });
});

test("v1：预览对应的 Plan 可直接提交模拟任务，页面不调用旧接口", async ({
  page,
}) => {
  const legacy: string[] = [];
  page.on("request", (r) => {
    if (
      new URL(r.url()).pathname.startsWith("/api/") &&
      !new URL(r.url()).pathname.startsWith("/api/v1/")
    )
      legacy.push(r.url());
  });
  await page.goto("/");
  await page.getByRole("button", { name: "添加文本框", exact: true }).click();
  const editor = page.getByLabel("文本框内容", { exact: true });
  await editor.fill("甲乙");
  await editor.press("Escape");
  const write = page.getByRole("button", { name: "开始书写", exact: true });
  await expect(write).toBeEnabled();
  const response = page.waitForResponse(
    (r) => r.url().endsWith("/api/v1/jobs") && r.request().method() === "POST",
  );
  await write.click();
  const result = await response;
  expect(result.status()).toBe(202);
  expect(await result.json()).toMatchObject({ mode: "simulate" });
  await expect(page.locator(".task-bar")).toContainText(/完成/);
  expect(legacy).toEqual([]);
});

test("v1：提交响应丢失后刷新，使用原键找回原任务且只创建一次", async ({
  page,
  request,
}) => {
  const baseline = (await (await request.get("/api/v1/jobs?limit=100")).json())
    .data.length;
  let loseResponses = true;
  const keys: string[] = [];
  const plans: string[] = [];
  await page.route("**/api/v1/jobs", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    keys.push(route.request().headers()["idempotency-key"]);
    plans.push(route.request().postDataJSON().plan_id);
    const response = await route.fetch();
    if (loseResponses) await route.abort("failed");
    else await route.fulfill({ response });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "添加文本框", exact: true }).click();
  const editor = page.getByLabel("文本框内容", { exact: true });
  await editor.fill("甲乙");
  await editor.press("Escape");
  await page.getByRole("button", { name: "开始书写", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "找回上次任务", exact: true }),
  ).toBeVisible();
  await page.reload();
  loseResponses = false;
  await page.getByRole("button", { name: "找回上次任务", exact: true }).click();
  await expect(page.getByText(/已找回任务 #/)).toBeVisible();
  expect(new Set(keys).size).toBe(1);
  expect(new Set(plans).size).toBe(1);
  const jobs = (await (await request.get("/api/v1/jobs?limit=100")).json())
    .data;
  expect(jobs.length).toBe(baseline + 1);
  await expect
    .poll(
      async () =>
        (await (await request.get(`/api/v1/jobs/${jobs[0].id}`)).json()).status,
    )
    .toBe("succeeded");
  expect(
    await page.evaluate(() =>
      localStorage.getItem("pygmalion-pending-submission"),
    ),
  ).toBeNull();
});
