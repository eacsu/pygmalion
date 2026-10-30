import { useCallback, useEffect, useState } from "react";

export type JobStatus =
  | "queued"
  | "printing"
  | "done"
  | "failed"
  | "cancelled"
  | "cancelling"
  | "interrupted";
export interface Job {
  job_id: number;
  submission_id: number;
  title?: string;
  author?: string;
  status: JobStatus;
  sent: number;
  total: number;
  percent: number;
  message: string;
  dry_run?: boolean;
  started_at: string;
  finished_at: string;
}
export interface Jobs {
  current: Job | null;
  jobs: Job[];
  dry_run: boolean;
}
export interface Preview {
  plan_id: string;
  svg: string;
  font_size_mm: number;
  requested_size: number;
  shrunk: boolean;
  can_print: boolean;
  cells: number;
  strokes: number;
  missing: string[];
  warnings: string[];
  font: string;
  diagnostics?: import("./canvas").Diagnostic[];
  layout?: {
    element_id: string;
    regions: {
      row?: number;
      col?: number;
      lines: { text: string; x_mm: number; y_mm: number }[];
    }[];
  }[];
}
export interface Fonts {
  default: string;
  fonts: {
    id: string;
    label: string;
    available: boolean;
    chars: number;
    warning?: string;
  }[];
}
export interface Field {
  key: string;
  label: string;
  unit: string;
  min: number;
  max: number;
  step: number;
  help: string;
  value: number;
}
export interface Calibration {
  grid_mm: [number, number];
  paper_mm: [number, number];
  paper_offset_mm: [number, number];
  paper_bounds_mm: [number, number, number, number];
  paper_preset: string;
  fits: boolean;
  paper_presets: {
    id: string;
    name: string;
    group: string;
    width_mm: number;
    height_mm: number;
  }[];
}
export interface Machine {
  port: string;
  baud: number;
  state: Record<string, string>;
  firmware: string[];
  backup: string | null;
}
export interface Ports {
  configured_port: string;
  baud: number;
  ports: { device: string; description: string }[];
}

export class ApiError extends Error {
  constructor(
    message: string,
    public code: string,
    public requestId?: string,
  ) {
    super(message);
  }
}
export async function request<T>(
  path: string,
  method = "GET",
  data?: object,
  signal?: AbortSignal,
  headers: Record<string, string> = {},
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: {
      Accept: "application/json",
      ...(data === undefined ? {} : { "Content-Type": "application/json" }),
      ...headers,
    },
    body: data === undefined ? undefined : JSON.stringify(data),
    signal,
  });
  let result;
  try {
    result = await response.json();
  } catch {
    throw new ApiError(
      "接口响应无法读取",
      "invalid_response",
      response.headers.get("X-Request-ID") || undefined,
    );
  }
  if (!response.ok)
    throw new ApiError(
      result.error?.message || `请求失败（${response.status}）`,
      result.error?.code || "request_failed",
      result.request_id,
    );
  return result as T;
}
export async function api<T>(
  path: string,
  data?: object,
  signal?: AbortSignal,
): Promise<T> {
  return request<T>(path, data === undefined ? "GET" : "POST", data, signal);
}

export function useResource<T>(path: string | null, interval = 0) {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{
    path: string;
    data?: T;
    error?: string;
  }>();
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    let fetching = false;
    async function refresh() {
      if (fetching || controller.signal.aborted || !path) return;
      fetching = true;
      try {
        const data = await api<T>(path, undefined, controller.signal);
        if (!controller.signal.aborted) setState({ path, data });
      } catch (error) {
        if (!controller.signal.aborted)
          setState((previous) => ({
            path,
            data: previous?.path === path ? previous.data : undefined,
            error: error instanceof Error ? error.message : "连接失败",
          }));
      } finally {
        fetching = false;
      }
    }
    void refresh();
    const timer = interval
      ? window.setInterval(() => void refresh(), interval)
      : undefined;
    return () => {
      controller.abort();
      if (timer) window.clearInterval(timer);
    };
  }, [path, interval, revision]);
  const reload = useCallback(() => setRevision((value) => value + 1), []);
  const current = state?.path === path ? state : undefined;
  return {
    data: current?.data,
    error: current?.error,
    loading: !!path && !current,
    reload,
  };
}

// HTTP 契约来自 OpenAPI；以下转换只服务现有界面的显示模型。
import type { components } from "./generated/api";
export type PublicPlan = components["schemas"]["Plan"];
export type PublicJob = components["schemas"]["Job"];
export type PublicOperation = components["schemas"]["Operation"];
export type PublicDeviceResult = components["schemas"]["DeviceResult"];
export type PublicMachine = components["schemas"]["MachineSnapshot"];
export type PublicSession = components["schemas"]["Session"];
export type Config<T> = {
  values: T;
  etag: string;
  fields: Field[];
  paper_presets: Calibration["paper_presets"];
};
export type Mode = "execute" | "simulate";

export async function idempotent<T>(
  path: string,
  data: object,
  key: string,
  signal?: AbortSignal,
): Promise<T> {
  try {
    return await request<T>(path, "POST", data, signal, {
      "Idempotency-Key": key,
    });
  } catch (error) {
    if (error instanceof TypeError && !signal?.aborted)
      return request<T>(path, "POST", data, signal, { "Idempotency-Key": key });
    throw error;
  }
}
export async function patchConfig<T>(
  path: string,
  values: object,
  etag?: string,
): Promise<Config<T>> {
  const current = etag ? { etag } : await api<Config<T>>(path);
  return request<Config<T>>(path, "PATCH", values, undefined, {
    "If-Match": current.etag,
  });
}
export async function deviceOperation(
  path: string,
  data: object,
  signal?: AbortSignal,
): Promise<PublicDeviceResult> {
  let operation = await idempotent<PublicOperation>(
    path,
    data,
    crypto.randomUUID(),
    signal,
  );
  const deadline = Date.now() + 75000;
  while (["queued", "running", "cancelling"].includes(operation.status)) {
    if (Date.now() > deadline)
      throw new ApiError(
        `操作等待超时，请查询 ${operation.id}`,
        "operation_timeout",
      );
    await new Promise((resolve) => setTimeout(resolve, 100));
    operation = await api<PublicOperation>(
      `/api/v1/operations/${operation.id}`,
      undefined,
      signal,
    );
  }
  if (operation.status !== "succeeded")
    throw new ApiError(
      `${operation.error?.message || "设备操作未完成"}（${operation.id}）`,
      operation.error?.code || operation.status,
    );
  return operation.result!;
}
export async function detectAndSelect() {
  const result = await deviceOperation("/api/v1/serial-probes", {});
  const matches = (result.ports || []).filter((port) => port.grbl);
  if (matches.length !== 1)
    throw new Error(
      matches.length
        ? "检测到多个 GRBL 设备，请手动选择"
        : "未检测到可用的 GRBL 书写机",
    );
  await patchConfig("/api/v1/machine/connection", { port: matches[0].device });
  return { port: matches[0].device };
}
export async function submitPlan(plan_id: string, mode: Mode) {
  const storageKey = "pygmalion-pending-submission";
  const previous = localStorage.getItem(storageKey);
  const receipt: { key: string; body: { plan_id: string; mode: Mode } } =
    previous
      ? JSON.parse(previous)
      : { key: crypto.randomUUID(), body: { plan_id, mode } };
  localStorage.setItem(storageKey, JSON.stringify(receipt));
  try {
    const result = await idempotent<PublicJob>(
      "/api/v1/jobs",
      receipt.body,
      receipt.key,
    );
    localStorage.removeItem(storageKey);
    return result;
  } catch (error) {
    // 已收到确定的业务拒绝时可修正重交；网络失联保留原键找回结果。
    if (
      error instanceof ApiError &&
      !["internal_error", "invalid_response"].includes(error.code)
    )
      localStorage.removeItem(storageKey);
    throw error;
  }
}
export function usePorts(interval = 0) {
  const ports = useResource<{ data: Ports["ports"] }>(
    "/api/v1/serial-ports",
    interval,
  );
  const connection = useResource<Config<{ port: string; baud: number }>>(
    "/api/v1/machine/connection",
    interval,
  );
  const reloadListing = ports.reload,
    reloadConnection = connection.reload;
  const reload = useCallback(() => {
    reloadListing();
    reloadConnection();
  }, [reloadListing, reloadConnection]);
  return {
    data:
      ports.data && connection.data
        ? {
            ports: ports.data.data,
            configured_port: connection.data.values.port,
            baud: connection.data.values.baud,
          }
        : undefined,
    error: ports.error || connection.error,
    loading: ports.loading || connection.loading,
    reload,
  };
}
export function useJobs(interval = 500) {
  const resource = useResource<{ data: PublicJob[] }>(
    "/api/v1/jobs?limit=100",
    interval,
  );
  const capability = useResource<{ allowed_job_modes: Mode[] }>(
    "/api/v1/capabilities",
  );
  const jobs = resource.data?.data.map((job): Job => ({
    job_id: job.id,
    submission_id: 0,
    title: job.title,
    status:
      job.status === "running"
        ? "printing"
        : job.status === "succeeded"
          ? "done"
          : job.status,
    sent: job.sent,
    total: job.total,
    percent: job.percent,
    message: job.message || job.error?.message || "",
    dry_run: job.mode === "simulate",
    started_at: job.started_at || "",
    finished_at: job.finished_at || "",
  }));
  return {
    data:
      jobs && capability.data
        ? {
            jobs,
            current:
              jobs.find((job) =>
                ["queued", "printing", "cancelling"].includes(job.status),
              ) || null,
            dry_run: !capability.data.allowed_job_modes.includes("execute"),
          }
        : undefined,
    loading: resource.loading || capability.loading,
    error: resource.error || capability.error,
    reload: resource.reload,
  };
}
export function useSoftwareConfig() {
  return useResource<Config<Record<string, number>>>(
    "/api/v1/settings/software",
  );
}
export function useCalibration() {
  const resource = useResource<
    Config<Record<string, number | string | boolean>>
  >("/api/v1/settings/calibration");
  const v = resource.data?.values;
  const data: Calibration | undefined = v
    ? {
        grid_mm: [Number(v.grid_width_mm), Number(v.grid_height_mm)],
        paper_mm: [Number(v.width_mm), Number(v.height_mm)],
        paper_offset_mm: [
          Number(v.paper_offset_x_mm),
          Number(v.paper_offset_y_mm),
        ],
        paper_bounds_mm: [
          Number(v.paper_min_x_mm),
          Number(v.paper_min_y_mm),
          Number(v.grid_width_mm),
          Number(v.grid_height_mm),
        ],
        paper_preset: String(v.paper_preset),
        fits: true,
        paper_presets: resource.data!.paper_presets,
      }
    : undefined;
  return { ...resource, data, etag: resource.data?.etag };
}
export function machineView(value: PublicMachine): Machine {
  return {
    port: value.port || "",
    baud: value.baud,
    state: value.state || {},
    firmware: value.firmware || [],
    backup: null,
  };
}
