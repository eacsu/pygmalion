import { expect, test, type Page, type WebSocketRoute } from "@playwright/test";

const machine = {
  port: "COM17",
  baud: 115200,
  state: { state: "Idle", MPos: "0,0,0" },
  firmware: ["[VER:1.1:test]"],
  connected: true,
  sampled_at: "2026-10-30T00:00:00Z",
  stale: false,
};
async function controls(page: Page) {
  const commands: {
    type: string;
    axis: string;
    distance_mm: number;
    session_id: string;
  }[] = [];
  const operations = new Map<string, object>();
  const releases: string[] = [];
  let peer: WebSocketRoute | undefined;
  let connections = 0;
  await page.routeWebSocket("**/api/v1/events", (socket) => {
    connections++;
    peer = socket;
  });
  await page.route("**/api/v1/machine/control-sessions", (route) =>
    route.fulfill({
      json: {
        id: "session_1",
        status: "active",
        expires_at: "2099-01-01T00:00:00Z",
      },
    }),
  );
  await page.route("**/api/v1/machine/control-sessions/session_1", (route) => {
    releases.push("release");
    return route.fulfill({ json: { id: "session_1", status: "released" } });
  });
  await page.route("**/api/v1/machine/refresh", (route) =>
    route.fulfill({
      json: {
        id: "refresh",
        status: "succeeded",
        result: { kind: "refresh", machine },
      },
    }),
  );
  await page.route("**/api/v1/machine/commands", (route) => {
    commands.push(route.request().postDataJSON());
    const id = `op_${commands.length}`;
    operations.set(id, { id, status: "running" });
    return route.fulfill({ json: operations.get(id) });
  });
  await page.route("**/api/v1/operations/*", (route) =>
    route.fulfill({
      json: operations.get(route.request().url().split("/").pop()!),
    }),
  );
  return {
    commands,
    operations,
    releases,
    peer: () => peer!,
    connections: () => connections,
  };
}

test("连续点动通过带会话的 HTTP 操作执行，WebSocket 只推送状态", async ({
  page,
}) => {
  const mock = await controls(page);
  await page.goto("/admin/machine");
  await page.getByRole("button", { name: "读取设备状态" }).click();
  await page.getByLabel("单次移动").selectOption("1");
  for (const name of [
    "X 正向移动 1 毫米",
    "Y 正向移动 1 毫米",
    "X 负向移动 1 毫米",
  ])
    await page.getByRole("button", { name }).click();
  await expect.poll(() => mock.commands.length).toBe(3);
  expect(
    mock.commands.map(({ axis, distance_mm }) => ({ axis, distance_mm })),
  ).toEqual([
    { axis: "x", distance_mm: 1 },
    { axis: "y", distance_mm: 1 },
    { axis: "x", distance_mm: -1 },
  ]);
  expect(mock.commands.every((c) => c.session_id === "session_1")).toBe(true);
  await expect(
    page.getByRole("button", { name: "读取设备状态" }),
  ).toBeDisabled();
  for (const [id] of mock.operations)
    mock.operations.set(id, {
      id,
      status: "succeeded",
      result: {
        kind: "command",
        machine: { ...machine, state: { state: "Idle", MPos: "0,1,0" } },
      },
    });
  await expect(page.locator(".coordinates strong").nth(1)).toHaveText("1");
  mock
    .peer()
    .send(
      JSON.stringify({
        type: "machine.updated",
        data: { ...machine, state: { state: "Idle", MPos: "2,3,0" } },
      }),
    );
  await expect(page.locator(".coordinates strong").first()).toHaveText("2");
  expect(mock.connections()).toBe(1);
});

test("观察通道重连查询快照，不重新发送运动命令", async ({ page }) => {
  const mock = await controls(page);
  await page.route("**/api/v1/machine", (route) =>
    route.fulfill({ json: machine }),
  );
  await page.goto("/admin/machine");
  await page.getByRole("button", { name: "读取设备状态" }).click();
  await page.getByRole("button", { name: "X 正向移动 5 毫米" }).click();
  await expect.poll(() => mock.commands.length).toBe(1);
  mock.peer().close();
  mock.operations.set("op_1", {
    id: "op_1",
    status: "succeeded",
    result: { kind: "command", machine },
  });
  await expect.poll(() => mock.connections()).toBe(2);
  expect(mock.commands.length).toBe(1);
});

test("扫描前显式释放控制会话，扫描结果经独立配置更新", async ({ page }) => {
  const mock = await controls(page);
  await page.route("**/api/v1/serial-probes", (route) => {
    expect(mock.releases).toEqual(["release"]);
    return route.fulfill({
      json: {
        id: "probe",
        status: "succeeded",
        result: { kind: "probe", ports: [{ device: "COM17", grbl: true }] },
      },
    });
  });
  await page.route("**/api/v1/machine/connection", (route) =>
    route.fulfill({
      json: { values: { port: "COM17", baud: 115200 }, etag: '"test"' },
    }),
  );
  await page.goto("/admin/machine");
  await page.getByRole("button", { name: "读取设备状态" }).click();
  await expect(
    page.getByRole("button", { name: "断开连接", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "检测串口" }).click();
  await expect(page.getByText("设备已检测：COM17")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "断开连接", exact: true }),
  ).toBeDisabled();
});
