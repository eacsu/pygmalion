import { test, expect } from "@playwright/test";

test("运行时显示可读进度与倒计时，发送100%仍等待设备；完成后固定用时", async ({
  page,
}) => {
  const status = "running";
  let percent = 42;
  const started = new Date(Date.now() - 5000).toISOString();
  await page.route("**/api/v1/jobs?*", (route) =>
    route.fulfill({
      json: {
        data: [
          {
            id: 9876,
            status,
            mode: "execute",
            title: "书写任务",
            started_at: started,
            finished_at:
              status === "succeeded"
                ? new Date(Date.parse(started) + 8000).toISOString()
                : null,
            sent: percent,
            total: 100,
            percent,
            estimated_duration_seconds: 120,
          },
        ],
      },
    }),
  );
  await page.goto("/");
  const bar = page.getByRole("progressbar", {
    name: "指令发送进度",
    exact: true,
  });
  await expect(bar).toHaveAttribute("value", "42");
  await expect(page.locator(".task-time")).toContainText("预计剩余约");
  await expect(page.locator(".task-time")).toContainText("已用");
  const first = await page.locator(".task-time").innerText();
  await expect
    .poll(() => page.locator(".task-time").innerText())
    .not.toBe(first);
  percent = 100;
  await expect(bar).toHaveAttribute("value", "100");
  await expect(page.locator(".task-progress-label")).toContainText(
    "等待设备完成",
  );
  await expect(
    page.getByRole("button", { name: "停止书写", exact: true }),
  ).toBeEnabled();
  await page.screenshot({ path: "/tmp/pygmalion-task-progress.png" });
  await page.getByRole("button", { name: "展开导航", exact: true }).click();
  await page.getByRole("link", { name: "参数设置", exact: true }).click();
  await expect(bar).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(bar).toBeVisible();
  const box = await bar.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: "/tmp/pygmalion-task-progress-mobile.png" });
});

test("预览可见预计用时，演练说明为预计实机时间", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "添加表格", exact: true }).click();
  await expect(page.locator(".inspector-preview")).toContainText("预计用时约");
  await page.getByRole("button", { name: "开始书写", exact: true }).click();
  await expect(page.locator(".task-time")).toContainText(/预计实机约|实际用时/);
  await expect(page.locator(".task-progress-title")).toContainText("书写完成");
  await expect(page.locator(".task-time")).toContainText("实际用时");
});

test("旧任务没有估算数据时不编造倒计时，停止中只显示等待停止确认", async ({
  page,
}) => {
  let status = "running";
  await page.route("**/api/v1/jobs?*", (route) =>
    route.fulfill({
      json: {
        data: [
          {
            id: 8765,
            status,
            mode: "execute",
            started_at: new Date(Date.now() - 3000).toISOString(),
            percent: 10,
            sent: 1,
            total: 10,
          },
        ],
      },
    }),
  );
  await page.goto("/");
  await expect(page.locator(".task-time")).toContainText("预计时间暂不可用");
  status = "cancelling";
  await expect(page.locator(".task-time")).toContainText("等待停止确认");
});

test("停止确认后隐藏发送进度与预估，保留停止结果", async ({ page }) => {
  let status = "running";
  let submitted = false;
  const job = () => ({
    id: 9901,
    status,
    mode: "simulate",
    title: "停止测试",
    started_at: new Date(Date.now() - 5000).toISOString(),
    finished_at: status === "cancelled" ? new Date().toISOString() : null,
    sent: 42,
    total: 100,
    percent: 42,
    estimated_duration_seconds: 100,
  });
  await page.route("**/api/v1/jobs?*", (route) =>
    route.fulfill({ json: { data: submitted ? [job()] : [] } }),
  );
  await page.route("**/api/v1/jobs", (route) => {
    submitted = true;
    return route.fulfill({ json: job() });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "添加表格", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "开始书写", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "开始书写", exact: true }).click();
  await expect(
    page.getByRole("progressbar", { name: "指令发送进度" }),
  ).toBeVisible();
  status = "cancelled";
  await expect(
    page.getByRole("progressbar", { name: "指令发送进度" }),
  ).toHaveCount(0);
  await expect(page.locator(".task-progress-title")).toContainText("已中止");
  await expect(page.locator(".task-time")).not.toContainText("预计");
  await page.screenshot({ path: "/tmp/pygmalion-stopped-progress.png" });
});
