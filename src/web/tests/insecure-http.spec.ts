import { expect, test } from "@playwright/test";

test("HTTP without randomUUID can open the editor and add a table", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => {
    Object.defineProperty(Crypto.prototype, "randomUUID", { value: undefined });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "添加表格", exact: true }).click();
  await expect(page.getByRole("gridcell", { name: /^单元格 1行1列/ })).toBeVisible();
  expect(errors).toEqual([]);
});
