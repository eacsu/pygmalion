import { test, expect } from "@playwright/test";

for (const mode of ["unique", "multiple", "manual", "none"] as const) {
  test(`工作台自动检测机器：${mode}`, async ({ page, request }) => {
    let configured = mode === "manual" ? "/dev/ttyUSB1" : "auto";
    let scans = 0;
    await page.route("**/api/v1/serial-ports", (route) =>
      route.fulfill({
        json: {
          data:
            mode === "none"
              ? []
              : [{ device: "/dev/ttyUSB0", description: "USB Serial" }],
        },
      }),
    );
    await page.route("**/api/v1/machine/connection", async (route) => {
      if (route.request().method() === "PATCH")
        configured = route.request().postDataJSON().port;
      await route.fulfill({
        json: {
          values: { port: configured, baud: 115200 },
          etag: '"test"',
          fields: [],
          paper_presets: [],
        },
      });
    });
    await page.route("**/api/v1/serial-probes", (route) => {
      scans++;
      return route.fulfill({
        json: {
          id: "probe",
          status: "succeeded",
          result: {
            kind: "probe",
            ports: [
              { device: "/dev/ttyUSB0", grbl: true },
              ...(mode === "multiple"
                ? [{ device: "/dev/ttyUSB2", grbl: true }]
                : []),
            ],
          },
        },
      });
    });
    await page.goto("/");
    await expect(page.locator(".header-device")).toContainText(
      mode === "unique"
        ? "设备就绪"
        : mode === "multiple"
          ? "多个 GRBL"
          : mode === "manual"
            ? "已选择 /dev/ttyUSB1"
            : "未检测到书写机",
    );
    expect(scans).toBe(mode === "manual" || mode === "none" ? 0 : 1);
    if (mode !== "unique") return;
    await page.getByRole("button", { name: "添加文本框", exact: true }).click();
    const editor = page.getByRole("textbox", {
      name: "文本框内容",
      exact: true,
    });
    await editor.fill("甲乙");
    await editor.press("Escape");
    const write = page.getByRole("button", { name: "开始书写", exact: true });
    await expect(write).toBeEnabled();
    const response = page.waitForResponse(
      (r) =>
        r.url().endsWith("/api/v1/jobs") && r.request().method() === "POST",
    );
    await write.click();
    const job = await (await response).json();
    expect(job).toMatchObject({ mode: "simulate" });
    await expect
      .poll(
        async () =>
          (await (await request.get(`/api/v1/jobs/${job.id}`)).json()).status,
      )
      .toBe("succeeded");
    expect(new URL(page.url()).pathname).toBe("/");
  });
}
