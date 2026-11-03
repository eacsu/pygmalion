import { test, expect } from "@playwright/test";

test("设计稿纵向工具与纸面同高，默认字号入口可用", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "添加表格", exact: true }),
  ).toBeEnabled();
  const tools = page.locator(".canvas-tools");
  const paper = page.locator(".page-preview");
  const toolbar = await tools.boundingBox();
  const canvas = await paper.boundingBox();
  expect(toolbar!.width).toBe(112);
  expect(canvas!.y).toBe(toolbar!.y);
  expect(canvas!.x).toBe(toolbar!.x + toolbar!.width);
  await expect(page.locator(".task-bar")).toBeHidden();
  await page.getByRole("button", { name: "默认字号", exact: true }).click();
  await expect(page.locator(".editor-defaults input")).toBeFocused();
  await page.getByRole("button", { name: "添加表格", exact: true }).click();
  await page.screenshot({ path: "/tmp/pygmalion-layout-light.png" });
  await page.getByRole("button", { name: "切换为夜间主题" }).click();
  await page.screenshot({ path: "/tmp/pygmalion-layout-dark.png" });
});

test("新版主菜单就地开合，Esc 恢复焦点，导航正常", async ({ page }) => {
  await page.goto("/");
  const menu = page.getByRole("button", { name: "展开导航", exact: true });
  const before = await page.locator(".page-preview").boundingBox();
  await menu.click();
  await expect(
    page.getByRole("navigation", { name: "工作区导航" }),
  ).toBeVisible();
  expect(await page.locator(".page-preview").boundingBox()).toEqual(before);
  await page.keyboard.press("Escape");
  await expect(menu).toBeFocused();
  await menu.click();
  await page.getByRole("link", { name: "参数设置", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "保存软件参数" }),
  ).toBeVisible();
  await expect(page.locator(".app-menu")).toHaveCount(0);
});
