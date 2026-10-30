import {
  test,
  expect,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

async function stored(page: Page) {
  return page.evaluate(() =>
    JSON.parse(localStorage.getItem("pygmalion-document-v2")!),
  );
}

async function defaults(request: APIRequestContext, font_size_mm: number) {
  const current = await (await request.get("/api/v1/settings/editor")).json();
  expect(
    (
      await request.patch("/api/v1/settings/editor", {
        data: { font_size_mm },
        headers: { "If-Match": current.etag },
      })
    ).ok(),
  ).toBe(true);
}
test.beforeEach(async ({ request }) => {
  await defaults(request, 8);
});
test.afterEach(async ({ request }) => {
  await defaults(request, 8);
});

test("全局默认字号持久保存，各框可独立编辑、撤销且不受默认值变更影响", async ({
  page,
}) => {
  await page.goto("/");
  const defaults = page.getByLabel("默认字号", { exact: true });
  await expect(defaults).toHaveValue("8");
  await defaults.fill("6.5");
  await page.getByRole("button", { name: "保存默认字号", exact: true }).click();
  await expect(page.locator(".editor-defaults summary")).toContainText(
    "6.5 mm",
  );
  await page.reload();
  await expect(defaults).toHaveValue("6.5");
  await page.getByRole("button", { name: "添加文本框", exact: true }).click();
  const editor = page.getByLabel("文本框内容", { exact: true });
  await editor.fill("甲");
  await editor.press("Escape");
  const size = page.getByLabel("字号", { exact: true });
  await expect(size).toHaveValue("6.5");
  await size.fill("10");
  await size.press("Tab");
  await page.getByRole("button", { name: "添加文本框", exact: true }).click();
  await editor.fill("乙");
  await editor.press("Escape");
  expect(
    (await stored(page)).elements.map(
      (element: { font_size_mm: number }) => element.font_size_mm,
    ),
  ).toEqual([10, 6.5]);
  await size.fill("12");
  await size.press("Control+z");
  await expect(size).toHaveValue("6.5");
  await size.press("Control+y");
  await expect(size).toHaveValue("12");
  await size.press("Tab");
  await expect(page.locator(".inline-preview-status")).toContainText(
    "内容位于可书写区域内",
  );
  await page.locator(".editor-defaults summary").click();
  await defaults.fill("9");
  await page.getByRole("button", { name: "保存默认字号", exact: true }).click();
  await expect(page.locator(".editor-defaults summary")).toContainText("9 mm");
  expect(
    (await stored(page)).elements.map(
      (element: { font_size_mm: number }) => element.font_size_mm,
    ),
  ).toEqual([10, 12]);
  await page.screenshot({
    path: test.info().outputPath("font-sizes-vallum.png"),
  });
  await page
    .getByRole("button", { name: "切换为夜间主题", exact: true })
    .click();
  await page.screenshot({
    path: test.info().outputPath("font-sizes-abyssus.png"),
  });
  await page.reload();
  await page.getByRole("button", { name: "文本框：甲", exact: true }).click();
  await expect(size).toHaveValue("10");
  await page.getByRole("button", { name: "添加文本框", exact: true }).click();
  await expect(size).toHaveValue("9");
  await page.getByRole("button", { name: "添加表格", exact: true }).click();
  await expect(size).toHaveValue("9");
});

test("默认字号保存失败保留草稿，可重试；非法默认值不破坏现有文档", async ({
  page,
}) => {
  let fail = true;
  await page.route("**/api/v1/settings/editor", async (route) => {
    if (route.request().method() !== "PATCH" || !fail) return route.continue();
    await route.fulfill({
      status: 503,
      json: {
        error: { code: "test_failure", message: "默认字号保存失败，请重试" },
      },
    });
  });
  await page.goto("/");
  const defaults = page.getByLabel("默认字号", { exact: true });
  await defaults.fill("999");
  await expect(defaults).toHaveAttribute("aria-invalid", "true");
  await expect(
    page.getByRole("button", { name: "保存默认字号", exact: true }),
  ).toBeDisabled();
  await defaults.fill("6");
  await page.getByRole("button", { name: "保存默认字号", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "默认字号保存失败" }),
  ).toBeVisible();
  await expect(defaults).toHaveValue("6");
  await expect(page.locator(".editor-defaults summary")).toContainText("8 mm");
  fail = false;
  await page.getByRole("button", { name: "保存默认字号", exact: true }).click();
  await expect(page.locator(".editor-defaults summary")).toContainText("6 mm");
  await page.getByRole("button", { name: "添加文本框", exact: true }).click();
  await expect(page.getByLabel("字号", { exact: true })).toHaveValue("6");
});

test("读取默认字号失败需明确重试，新建不会悄悄使用其他字号", async ({
  page,
}) => {
  let fail = true;
  await page.route("**/api/v1/settings/editor", async (route) => {
    if (!fail) return route.continue();
    await route.fulfill({
      status: 503,
      json: { error: { code: "test_failure", message: "默认字号读取失败" } },
    });
  });
  await page.goto("/");
  await expect(
    page.locator(".editor-defaults").getByRole("alert"),
  ).toContainText("默认字号读取失败");
  await expect(
    page.getByRole("button", { name: "添加文本框", exact: true }),
  ).toBeDisabled();
  fail = false;
  await page
    .locator(".editor-defaults")
    .getByRole("button", { name: "重试", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "添加文本框", exact: true }),
  ).toBeEnabled();
});

test("导入 TXT 使用全局默认字号，打开 JSON 保留文档字号", async ({
  page,
  request,
}) => {
  await defaults(request, 6);
  await page.goto("/");
  await expect(page.getByLabel("默认字号", { exact: true })).toHaveValue("6");
  await page.getByLabel("文档文件", { exact: true }).setInputFiles({
    name: "稿件.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("甲乙"),
  });
  await expect
    .poll(async () => (await stored(page)).elements[0]?.font_size_mm)
    .toBe(6);
  const document = await stored(page);
  document.elements[0].font_size_mm = 12;
  await page.getByLabel("文档文件", { exact: true }).setInputFiles({
    name: "已排版.pygmalion.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(document)),
  });
  await expect
    .poll(async () => (await stored(page)).elements[0]?.font_size_mm)
    .toBe(12);
  await page.getByRole("button", { name: "文本框：甲乙", exact: true }).click();
  await expect(page.getByLabel("字号", { exact: true })).toHaveValue("12");
});
