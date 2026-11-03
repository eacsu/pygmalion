import { test, expect, type Page } from "@playwright/test";

async function ready(page: Page) {
  await expect(page.locator(".document-save-status")).toContainText(
    "已保存到服务端",
  );
  return new URL(page.url()).searchParams.get("document")!;
}

test("文档由数据库保存，不同客户端与外部工具修改能同步到页面", async ({
  page,
  browser,
  request,
}) => {
  await page.goto("/");
  const id = await ready(page);
  await page.getByLabel("文档名称", { exact: true }).fill("共享排版");
  await ready(page);
  await page.getByRole("button", { name: "添加文本框", exact: true }).click();
  await page.getByLabel("文本框内容", { exact: true }).fill("甲乙");
  await page.getByLabel("文本框内容", { exact: true }).press("Escape");
  await ready(page);
  const context = await browser.newContext();
  const other = await context.newPage();
  try {
    await other.goto(page.url());
    await ready(other);
    await expect(other.getByLabel("文档名称", { exact: true })).toHaveValue(
      "共享排版",
    );
    await expect(
      other.getByRole("button", { name: "文本框：甲乙", exact: true }),
    ).toBeVisible();
    const stored = await (await request.get(`/api/v1/documents/${id}`)).json();
    const edited = {
      ...stored.document,
      name: "外部智能体调整",
      elements: [{ ...stored.document.elements[0], x_mm: -30 }],
    };
    expect(
      (
        await request.put(`/api/v1/documents/${id}`, {
          data: edited,
          headers: { "If-Match": `"${stored.revision}"` },
        })
      ).ok(),
    ).toBe(true);
    await expect(page.getByLabel("文档名称", { exact: true })).toHaveValue(
      "外部智能体调整",
    );
    await expect(other.getByLabel("文档名称", { exact: true })).toHaveValue(
      "外部智能体调整",
    );
    // 清空全部浏览器缓存后，URL 中的文档仍从数据库恢复。
    await other.evaluate(() => localStorage.clear());
    await other.reload();
    await ready(other);
    await expect(other.getByLabel("文档名称", { exact: true })).toHaveValue(
      "外部智能体调整",
    );
    await page.getByRole("button", { name: "打开", exact: true }).click();
    await expect(page.getByRole("dialog")).toHaveText(/实例文档库/);
    await expect(
      page
        .getByRole("dialog")
        .getByRole("button", { name: "外部智能体调整 · 当前", exact: true }),
    ).toBeVisible();
    await page.screenshot({ path: "/tmp/pygmalion-document-library.png" });
  } finally {
    await context.close();
  }
});

test("并发保存发生冲突时保留本页修改，可以另存为独立文档", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const id = await ready(page);
  let unblock: (() => void) | undefined;
  let waiting = false;
  await page.route(`**/api/v1/documents/${id}`, async (route) => {
    if (route.request().method() !== "PUT") return route.continue();
    waiting = true;
    await new Promise<void>((resolve) => {
      unblock = resolve;
    });
    await route.continue();
  });
  await page.getByLabel("文档名称", { exact: true }).fill("保留本页版本");
  await expect.poll(() => waiting).toBe(true);
  const current = await (await request.get(`/api/v1/documents/${id}`)).json();
  expect(
    (
      await request.put(`/api/v1/documents/${id}`, {
        data: { ...current.document, name: "他人已保存版本" },
        headers: { "If-Match": `"${current.revision}"` },
      })
    ).ok(),
  ).toBe(true);
  unblock!();
  await expect(page.locator(".document-sync-error")).toContainText(
    "其他客户端修改",
  );
  await expect(page.getByLabel("文档名称", { exact: true })).toHaveValue(
    "保留本页版本",
  );
  await page.getByRole("button", { name: "另存为新文档", exact: true }).click();
  await ready(page);
  expect(new URL(page.url()).searchParams.get("document")).not.toBe(id);
  await expect(page.getByLabel("文档名称", { exact: true })).toHaveValue(
    "保留本页版本",
  );
  expect(
    (await (await request.get(`/api/v1/documents/${id}`)).json()).document.name,
  ).toBe("他人已保存版本");
});

test("机器书写时其他客户端仍能编辑并加入公共队列", async ({ page }) => {
  const running = {
    id: 123450,
    status: "running",
    mode: "simulate",
    title: "另一位使用者",
    sent: 5,
    total: 100,
    percent: 5,
  };
  const queued: (typeof running)[] = [];
  await page.route("**/api/v1/queue", (route) =>
    route.fulfill({ json: { running, queued, queued_total: queued.length } }),
  );
  await page.route("**/api/v1/jobs?*", (route) =>
    route.fulfill({ json: { data: [running, ...queued] } }),
  );
  await page.route("**/api/v1/jobs", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    const body = route.request().postDataJSON();
    queued.push({
      ...running,
      id: 123451 + queued.length,
      status: "queued",
      title: "我的排版",
      mode: body.mode,
      sent: 0,
      percent: 0,
    });
    await route.fulfill({ status: 202, json: queued[queued.length - 1] });
  });
  await page.goto("/");
  await ready(page);
  await expect(
    page.getByRole("button", { name: "添加文本框", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "添加文本框", exact: true }).click();
  await page.getByLabel("文本框内容", { exact: true }).fill("甲");
  await page.getByLabel("文本框内容", { exact: true }).press("Escape");
  await page.getByRole("button", { name: "加入队列", exact: true }).click();
  await expect(
    page
      .locator(".task-inner")
      .getByRole("button", { name: "队列 1", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "加入队列", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "加入队列", exact: true }).click();
  await expect(
    page
      .locator(".task-inner")
      .getByRole("button", { name: "队列 2", exact: true }),
  ).toBeVisible();
  await page
    .locator(".task-inner")
    .getByRole("button", { name: "队列 2", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("等待 2 个任务");
  await expect(
    page.getByRole("button", { name: "取消排队", exact: true }),
  ).toHaveCount(2);
  await page.screenshot({ path: "/tmp/pygmalion-shared-queue.png" });
  await page.route("**/api/v1/jobs/123451/cancel", async (route) => {
    const [cancelled] = queued.splice(0, 1);
    await route.fulfill({ json: { ...cancelled, status: "cancelled" } });
  });
  await page
    .getByRole("button", { name: "取消排队", exact: true })
    .first()
    .click();
  await expect(page.getByRole("dialog")).toContainText("不影响正在运行的任务");
  await page.getByRole("button", { name: "确认取消排队", exact: true }).click();
  await expect(
    page
      .locator(".task-inner")
      .getByRole("button", { name: "队列 1", exact: true }),
  ).toBeVisible();
});

test("浏览器缓存写入失败不影响数据库保存", async ({ page, request }) => {
  await page.goto("/");
  const id = await ready(page);
  await page.evaluate(() => {
    const set = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (
        key.startsWith("pygmalion-document") ||
        key === "pygmalion-server-document"
      )
        throw new DOMException("缓存禁用", "QuotaExceededError");
      return set.call(this, key, value);
    };
  });
  await page.getByLabel("文档名称", { exact: true }).fill("数据库正式副本");
  await ready(page);
  expect(
    (await (await request.get(`/api/v1/documents/${id}`)).json()).document.name,
  ).toBe("数据库正式副本");
  await page.reload();
  await ready(page);
  await expect(page.getByLabel("文档名称", { exact: true })).toHaveValue(
    "数据库正式副本",
  );
});

test("旧浏览器缓存不能覆盖数据库新版本，断线草稿按版本恢复", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const id = await ready(page);
  await page.getByLabel("文档名称", { exact: true }).fill("数据库新版本");
  await ready(page);
  await page.evaluate(() => {
    const cached = JSON.parse(localStorage.getItem("pygmalion-document-v2")!);
    cached.name = "故意过期的旧缓存";
    localStorage.setItem("pygmalion-document-v2", JSON.stringify(cached));
  });
  await page.reload();
  await ready(page);
  await expect(page.getByLabel("文档名称", { exact: true })).toHaveValue(
    "数据库新版本",
  );
  await page.route(`**/api/v1/documents/${id}`, (route) =>
    route.request().method() === "PUT"
      ? route.abort("failed")
      : route.continue(),
  );
  await page.getByLabel("文档名称", { exact: true }).fill("断线时的草稿");
  await expect(page.locator(".document-sync-error")).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.reload();
  await expect(page.getByLabel("文档名称", { exact: true })).toHaveValue(
    "断线时的草稿",
  );
  await expect(page.locator(".document-sync-error")).toBeVisible();
  await page.getByRole("button", { name: "重试保存", exact: true }).focus();
  await page.unroute(`**/api/v1/documents/${id}`);
  await page.keyboard.press("Enter");
  await ready(page);
  expect(
    (await (await request.get(`/api/v1/documents/${id}`)).json()).document.name,
  ).toBe("断线时的草稿");
});
