import { test, expect } from "@playwright/test";

test("缺少字库立即报错，退出编辑后仍报错且禁止书写", async ({ page }) => {
  await page.route("**/api/v1/fonts", (route) =>
    route.fulfill({ json: { ok: true, default: "", fonts: [] } }),
  );
  await page.route("**/api/v1/plans", (route) =>
    route.fulfill({
      status: 400,
      json: { error: { code: "test_failure", message: "未找到书写字库" } },
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "添加文本框", exact: true }).click();
  await expect(page.locator(".inline-preview-status")).toHaveAttribute(
    "role",
    "alert",
  );
  await expect(page.locator(".inline-preview-status")).toContainText(
    "未找到书写字库",
  );
  const editor = page.getByRole("textbox", { name: "文本框内容", exact: true });
  await editor.fill("今天的天气真好");
  await page.locator(".canvas-paper").click({ position: { x: 8, y: 8 } });
  await expect(editor).toHaveCount(0);
  await expect(page.locator(".inline-preview-status")).toContainText(
    "未找到书写字库",
  );
  await expect(
    page.getByRole("img", { name: "纸面真实笔画预览", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "开始书写", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "文本框：今天的天气真好", exact: true })
    .click();
  await expect(editor).toHaveValue("今天的天气真好");
  await page.screenshot({ path: test.info().outputPath("missing-font.png") });
});
