import { test, expect } from "@playwright/test";

test("截图中的速度可整组保存并重新读取", async ({ page }) => {
  await page.goto("/admin/settings");
  const original = await (
    await page.request.get("/api/v1/settings/software")
  ).json();
  try {
    for (const [label, value] of [
      ["书写速度", "12000"],
      ["空走速度", "12000"],
      ["抬落笔速度", "8000"],
    ])
      await page.getByLabel(label, { exact: true }).fill(value);
    await page
      .getByRole("button", { name: "保存软件参数", exact: true })
      .click();
    await expect(page.getByText("软件参数已保存")).toBeVisible();
    await page.reload();
    await expect(page.getByLabel("书写速度", { exact: true })).toHaveValue(
      "12000",
    );
    await expect(page.getByLabel("空走速度", { exact: true })).toHaveValue(
      "12000",
    );
    await expect(page.getByLabel("抬落笔速度", { exact: true })).toHaveValue(
      "8000",
    );
  } finally {
    const current = await (
      await page.request.get("/api/v1/settings/software")
    ).json();
    await page.request.patch("/api/v1/settings/software", {
      data: original.values,
      headers: { "If-Match": current.etag },
    });
  }
});

test("纸外负坐标、大尺寸和笔头定位可保存、刷新并生成真实预览", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "添加表格", exact: true }).click();
  await page.getByLabel("横向位置", { exact: true }).fill("-40");
  await page.getByLabel("纵向位置", { exact: true }).fill("330");
  await page.getByLabel("宽度", { exact: true }).fill("400");
  await expect(page.locator(".inline-preview-status")).toContainText(
    "内容校核通过",
  );
  await page.getByRole("button", { name: "笔头定位", exact: true }).click();
  await page.screenshot({ path: "/tmp/pygmalion-pen-nib.png" });
  await page.getByLabel("笔头 X", { exact: true }).fill("-50");
  await page.getByLabel("笔头 Y", { exact: true }).fill("400");
  await page.reload();
  await page.getByLabel("纸张", { exact: true }).selectOption("A5");
  const stored = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("pygmalion-document-v2")!),
  );
  expect(stored.elements[0]).toMatchObject({
    x_mm: -40,
    y_mm: 330,
    width_mm: 400,
  });
  expect(stored.pen_anchor).toEqual({ x_mm: -50, y_mm: 400 });
  const image = page.getByRole("img", {
    name: "纸面真实笔画预览",
    exact: true,
  });
  await expect(image).toBeVisible();
  const svg = await image.evaluate(async (img: HTMLImageElement) =>
    (await fetch(img.src)).text(),
  );
  expect(svg).toContain('viewBox="-40 0 400 390"');
  expect(svg).not.toContain("stroke-dasharray");
  await page.getByRole("button", { name: "小手工具 (H)" }).click();
  const stage = await page.locator(".canvas-stage").boundingBox();
  await page.mouse.move(
    stage!.x + stage!.width / 2,
    stage!.y + stage!.height / 2,
  );
  await page.mouse.down();
  await page.mouse.move(stage!.x + stage!.width / 2, stage!.y + 80, {
    steps: 5,
  });
  await page.mouse.up();
  await page.screenshot({ path: "/tmp/pygmalion-free-canvas.png" });
  await page.getByRole("button", { name: "切换为夜间主题" }).click();
  await expect(page.locator(".outside-paper-ink")).toBeVisible();
  await page.screenshot({ path: "/tmp/pygmalion-free-canvas-dark.png" });
});
