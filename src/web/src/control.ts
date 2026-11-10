import { randomId } from "./uuid";
import {
  api,
  ApiError,
  request,
  idempotent,
  deviceOperation,
  machineView,
  type PublicSession,
  type PublicMachine,
} from "./api";

export class ControlError extends Error {
  constructor(
    message: string,
    public cancelled = false,
  ) {
    super(message);
  }
}

/** 观察通道不持有设备；只有显式动作才取得有期限的控制会话。 */
export class MachineControl {
  private session: PublicSession | null = null;
  private connecting: Promise<PublicSession> | null = null;
  private socket: WebSocket | null = null;
  private heartbeat: ReturnType<typeof setInterval> | undefined;
  private generation = 0;
  private reconnect: ReturnType<typeof setTimeout> | undefined;
  constructor(
    private onState: (state: Record<string, string>) => void,
    private onError: (message: string) => void,
    private onDisconnect: () => void,
  ) {}
  private async connect() {
    if (this.session) return this.session;
    if (this.connecting) return this.connecting;
    const generation = this.generation;
    this.connecting = idempotent<PublicSession>(
      "/api/v1/machine/control-sessions",
      {},
      randomId(),
    )
      .then((session) => {
        if (generation !== this.generation) {
          void request(
            `/api/v1/machine/control-sessions/${session.id}`,
            "DELETE",
          ).catch(() => {});
          throw new ControlError("连接已取消", true);
        }
        this.session = session;
        this.heartbeat = setInterval(() => {
          void api<PublicSession>(
            `/api/v1/machine/control-sessions/${session.id}/renew`,
            {},
          ).catch((error) => {
            this.onError(error.message);
            this.close();
          });
        }, 10000);
        this.observe(generation);
        return session;
      })
      .finally(() => {
        this.connecting = null;
      });
    return this.connecting;
  }
  private observe(generation: number) {
    if (generation !== this.generation || !this.session) return;
    const url = new URL("/api/v1/events", window.location.href);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(url);
    this.socket = socket;
    socket.onmessage = (event) => {
      if (generation !== this.generation) return;
      try {
        const message = JSON.parse(event.data) as {
          type: string;
          data: PublicMachine;
        };
        if (message.type === "machine.updated") {
          if (message.data.connected) this.onState(message.data.state || {});
          else if (message.data.sampled_at)
            this.onError("设备连接已中断，请重新读取状态");
        }
      } catch {
        this.onError("设备状态消息无法读取");
      }
    };
    socket.onclose = () => {
      if (generation !== this.generation) return;
      this.reconnect = setTimeout(() => {
        void api<PublicMachine>("/api/v1/machine")
          .then((snapshot) => {
            if (generation === this.generation && snapshot.connected)
              this.onState(snapshot.state || {});
          })
          .catch(() => {});
        this.observe(generation);
      }, 1000);
    };
  }
  async request<T>(type: string, payload?: object): Promise<T> {
    if (type === "disconnect") {
      await this.disconnect();
      return {} as T;
    }
    const session = await this.connect();
    const body = payload as { action?: string; dist?: number } | undefined;
    let path = "/api/v1/machine/commands";
    let data: object;
    if (type === "inspect") {
      path = "/api/v1/machine/refresh";
      data = { session_id: session.id };
    } else if (type === "backup") {
      path = "/api/v1/machine/backups";
      data = { session_id: session.id };
    } else if (type === "jog") {
      const action = body?.action;
      data =
        action === "x" || action === "y"
          ? {
              type: "jog",
              axis: action,
              distance_mm: body?.dist,
              session_id: session.id,
            }
          : {
              type:
                action === "zero"
                  ? "set_origin"
                  : action === "goto_zero"
                    ? "goto_origin"
                    : action,
              session_id: session.id,
            };
    } else data = { type, session_id: session.id };
    let result;
    try {
      result = await deviceOperation(path, data);
    } catch (error) {
      if (error instanceof ApiError && error.code === "cancelled")
        throw new ControlError(error.message, true);
      throw error;
    }
    if (result.machine) this.onState(result.machine.state || {});
    return {
      ...(result.machine ? machineView(result.machine) : {}),
      backup: result.backup?.id,
      path: result.backup?.id,
    } as T;
  }
  async disconnect() {
    const session = this.session;
    this.close(false, false);
    if (session)
      await request(`/api/v1/machine/control-sessions/${session.id}`, "DELETE");
  }
  close(notify = true, release = true) {
    this.generation++;
    const session = this.session;
    this.session = null;
    if (this.reconnect) clearTimeout(this.reconnect);
    this.reconnect = undefined;
    if (this.heartbeat) clearInterval(this.heartbeat);
    this.heartbeat = undefined;
    this.socket?.close();
    this.socket = null;
    if (session && release)
      void request(
        `/api/v1/machine/control-sessions/${session.id}`,
        "DELETE",
      ).catch(() => {});
    if (notify) this.onDisconnect();
  }
}
