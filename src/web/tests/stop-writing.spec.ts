import { test, expect } from "@playwright/test";

test("顶栏在任务运行和收尾时切换停止状态，跨页可见，重复停止被阻止", async ({
  page,
}) => {
  let status = "running";
  let requests = 0;
  let accept: (() => void) | undefined;
  await page.route("**/api/v1/jobs?*", (route) =>
    route.fulfill({
      json: {
        data: [
          {
            id: 98765,
            status,
            mode: "simulate",
            title: "测试任务",
            sent: 1,
            total: 20,
            percent: 5,
          },
        ],
      },
    }),
  );
  await page.route("**/api/v1/jobs/98765/cancel", async (route) => {
    requests++;
    await new Promise<void>((resolve) => {
      accept = resolve;
    });
    status = "cancelling";
    await route.fulfill({ json: { id: 98765, status } });
  });
  await page.goto("/");
  const stop = page
    .locator(".header")
    .getByRole("button", { name: "停止书写", exact: true });
  await expect(stop).toBeEnabled();
  await expect(
    page.getByRole("button", { name: "开始书写", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "展开导航", exact: true }).click();
  await page.getByRole("link", { name: "参数设置", exact: true }).click();
  await expect(stop).toBeEnabled();
  await stop.click();
  await page
    .getByRole("button", { name: "确认中止", exact: true })
    .click({ noWaitAfter: true });
  const stopping = page
    .locator(".header")
    .getByRole("button", { name: "正在停止", exact: true });
  await expect(stopping).toBeDisabled();
  expect(requests).toBe(1);
  accept!();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(stopping).toBeDisabled();
  status = "cancelled";
  await expect(stopping).toHaveCount(0);
  await page.getByRole("button", { name: "展开导航", exact: true }).click();
  await page.getByRole("link", { name: "书写工作台", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "开始书写", exact: true }),
  ).toBeVisible();
  expect(requests).toBe(1);
});
