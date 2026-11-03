import { useEffect, useRef, useState } from "react";
import {
  api,
  useJobs,
  usePorts,
  detectAndSelect,
  type Job,
  type Mode,
  type PublicOperation,
} from "./api";
import { Button, Dialog, Link } from "./ui";
import { navigation } from "./navigation";
import { MachinePage, SettingsPage } from "./machine";
import { Workbench } from "./workbench";
import { useWorkbench } from "./useWorkbench";
import { DocumentLibrary } from "./DocumentLibrary";
import { JobQueue } from "./JobQueue";
import { TaskProgress } from "./TaskProgress";

export default function App() {
  const [documentHost, setDocumentHost] = useState<HTMLDivElement | null>(null);
  const [help, setHelp] = useState(false);
  const [library, setLibrary] = useState(false);
  const [queueOpen, setQueueOpen] = useState(false);
  const [deviceState, setDeviceState] = useState("设备状态未读取");
  const [path, setPath] = useState(window.location.pathname);
  const [night, setNight] = useState(() =>
    ["night", "abyssus"].includes(
      localStorage.getItem("pygmalion-theme") || "",
    ),
  );
  const [expanded, setExpanded] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!expanded) return;
    const dismiss = (event: PointerEvent) => {
      if (
        event.target instanceof Element &&
        !event.target.closest(".app-menu,.main-menu-toggle")
      )
        setExpanded(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setExpanded(false);
        menuButton.current?.focus();
      }
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", escape);
    };
  }, [expanded]);
  const [toast, setToast] = useState<{ text: string; error?: boolean }>();
  const [cancel, setCancel] = useState<Job>();
  const [stopRequested, setStopRequested] = useState<number>();
  const [estopping, setEstopping] = useState(false);
  const jobs = useJobs(500);
  const ports = usePorts(5000);
  const current =
    jobs.data?.current || jobs.data?.jobs.find((j) => j.status === "queued");
  const busy = !!current;
  const stopping =
    !!current &&
    (current.status === "cancelling" || stopRequested === current.job_id);
  const active = navigation.find((item) => item.href === path)?.key || "layout";
  const [detecting, setDetecting] = useState(false);
  const attemptedPorts = useRef("");
  const detectedPort = useRef("");
  const portKey = ports.data
    ? JSON.stringify(ports.data.ports.map((port) => port.device).sort())
    : "";
  const configuredPort = ports.data?.configured_port;
  const reloadPorts = ports.reload;
  useEffect(() => {
    if (active !== "layout" || busy || !portKey || !configuredPort) return;
    let cancelled = false;
    let finished = false;
    // 延迟到 effect 安装完成，避免 StrictMode 的重挂载触发两次串口探测。
    const timer = window.setTimeout(() => {
      setDetecting(false);
      // 手动指定的机器保留；自动检测成功的端口仍跟踪拔插。
      if (
        configuredPort !== "auto" &&
        configuredPort !== detectedPort.current
      ) {
        setDeviceState(`已选择 ${configuredPort}`);
        finished = true;
        return;
      }
      if (attemptedPorts.current === portKey) {
        finished = true;
        return;
      }
      attemptedPorts.current = portKey;
      if (portKey === "[]") {
        setDeviceState("未检测到书写机");
        finished = true;
        return;
      }
      setDetecting(true);
      setDeviceState("正在检测书写机…");
      void detectAndSelect()
        .then((result) => {
          if (cancelled) return;
          detectedPort.current = result.port;
          setDeviceState(`设备就绪 · ${result.port}`);
          reloadPorts();
        })
        .catch((error) => {
          if (!cancelled)
            setDeviceState(
              error instanceof Error ? error.message : "未检测到书写机",
            );
        })
        .finally(() => {
          finished = true;
          if (!cancelled) setDetecting(false);
        });
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      if (!finished) attemptedPorts.current = "";
    };
  }, [active, busy, portKey, configuredPort, reloadPorts]);
  const pageLabel = navigation.find((item) => item.key === active)!.label;
  const notify = (text: string, error = false) => setToast({ text, error });
  const [mode, setMode] = useState<Mode>("execute");
  const effectiveMode: Mode = jobs.data?.dry_run ? "simulate" : mode;
  const doc = useWorkbench({
    busy,
    mode: effectiveMode,
    jobs: jobs.data?.jobs,
    notify,
    refresh: jobs.reload,
  });
  const previousContext = useRef("");
  useEffect(() => {
    if (!configuredPort) return;
    const next = `${active}:${configuredPort}`;
    if (previousContext.current && previousContext.current !== next)
      doc.reload();
    previousContext.current = next;
  }, [active, configuredPort, doc]);
  const last = jobs.data?.jobs.find((j) => j.job_id === doc.jobId);
  useEffect(() => {
    const listener = () => {
      setPath(window.location.pathname);
      setExpanded(false);
    };
    window.addEventListener("popstate", listener);
    return () => window.removeEventListener("popstate", listener);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = night ? "abyssus" : "vallum";
    localStorage.setItem("pygmalion-theme", night ? "abyssus" : "vallum");
  }, [night]);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(
      () => setToast(undefined),
      toast.error ? 7000 : 3200,
    );
    return () => window.clearTimeout(timer);
  }, [toast]);
  async function estop() {
    setEstopping(true);
    try {
      const result = await api<PublicOperation>(
        "/api/v1/machine/emergency-stop",
        {},
      );
      notify(
        result.error?.message || "急停状态尚未确认",
        !result.result?.stop_confirmed,
      );
      jobs.reload();
    } catch (error) {
      notify(error instanceof Error ? error.message : "急停失败", true);
    } finally {
      setEstopping(false);
    }
  }
  return (
    <>
      <a href="#main" className="skip-link">
        跳到主要内容
      </a>
      <div
        className={`app-shell console-v1 ${expanded ? "nav-expanded" : "nav-collapsed"}`}
      >
        {expanded && (
          <nav className="app-menu" id="app-menu" aria-label="工作区导航">
            <strong>Pygmalion</strong>
            {navigation.map((item) => (
              <Link
                key={item.key}
                href={item.href}
                aria-current={active === item.key ? "page" : undefined}
              >
                {item.label}
              </Link>
            ))}
            <Button
              kind="ghost"
              onClick={() => {
                setExpanded(false);
                setLibrary(true);
              }}
            >
              文档库
            </Button>
            <Button
              kind="ghost"
              onClick={() => {
                setExpanded(false);
                setQueueOpen(true);
              }}
            >
              任务队列
            </Button>
            <Button
              kind="ghost"
              onClick={() => {
                setExpanded(false);
                menuButton.current?.focus();
              }}
            >
              关闭导航
            </Button>
          </nav>
        )}
        <div className="workspace">
          <header className="header">
            <div className="header-inner">
              <div className="breadcrumb">
                <button
                  ref={menuButton}
                  type="button"
                  className="main-menu-toggle"
                  aria-label={expanded ? "收起导航" : "展开导航"}
                  aria-expanded={expanded}
                  aria-controls="app-menu"
                  onClick={() => setExpanded(!expanded)}
                >
                  <img
                    src="/design/v1/menu-current.svg"
                    alt=""
                    width="28"
                    height="28"
                  />
                </button>
                <span>{active === "layout" ? "Pygmalion" : pageLabel}</span>
              </div>
              {active === "layout" && (
                <div className="document-host" ref={setDocumentHost} />
              )}
              <div className="header-actions">
                <Link
                  href="/admin/machine"
                  className="header-device"
                  title={`串口：${ports.data?.configured_port || "尚未读取"}`}
                >
                  ○{" "}
                  {jobs.error
                    ? "任务状态不可用"
                    : busy
                      ? "书写中"
                      : deviceState}
                </Link>
                <Button
                  kind="ghost"
                  onClick={() => setNight(!night)}
                  aria-label={`切换为${night ? "白昼" : "夜间"}主题`}
                >
                  主题
                </Button>
                {active === "layout" && (
                  <>
                    <select
                      aria-label="书写模式"
                      value={effectiveMode}
                      disabled={doc.writing || jobs.data?.dry_run}
                      onChange={(event) => setMode(event.target.value as Mode)}
                    >
                      <option value="execute">真实书写</option>
                      <option value="simulate">模拟书写</option>
                    </select>
                    {!current && (
                      <Button
                        className="start-writing"
                        kind="primary"
                        disabled={
                          doc.pendingSubmission
                            ? doc.writing
                            : !doc.canWrite ||
                              detecting ||
                              !!jobs.error ||
                              jobs.loading
                        }
                        onClick={() => void doc.write()}
                      >
                        {doc.writing
                          ? "正在准备"
                          : doc.pendingSubmission
                            ? "找回上次任务"
                            : busy
                              ? "书写中"
                              : "开始书写"}
                      </Button>
                    )}
                  </>
                )}
                {current && active === "layout" && (
                  <Button
                    kind="ghost"
                    disabled={!doc.canWrite || doc.writing || !!jobs.error}
                    onClick={() => void doc.write()}
                  >
                    {doc.pendingSubmission ? "找回上次任务" : "加入队列"}
                  </Button>
                )}
                {current && (
                  <Button
                    className="start-writing"
                    kind="primary"
                    disabled={stopping}
                    onClick={() => setCancel(current)}
                  >
                    {stopping ? "正在停止" : "停止书写"}
                  </Button>
                )}
                {active !== "layout" && !current && (
                  <span className="start-reserved" />
                )}
                <Button
                  kind="danger"
                  onClick={() => void estop()}
                  disabled={estopping}
                >
                  {estopping ? "急停中" : "急停"}
                </Button>
              </div>
            </div>
          </header>
          <main
            id="main"
            className={`main ${active === "layout" ? "workbench-main" : "utility-main"}`}
          >
            {active === "layout" ? (
              <Workbench
                model={doc}
                documentHost={documentHost}
                busy={busy}
                onHelp={() => setHelp(true)}
                onOpenLibrary={() => setLibrary(true)}
              />
            ) : (
              <div className="bounded">
                {active === "machine" ? (
                  <MachinePage
                    busy={busy}
                    notify={notify}
                    onState={setDeviceState}
                  />
                ) : (
                  <SettingsPage busy={busy} notify={notify} />
                )}
              </div>
            )}
          </main>
          <footer
            className="task-bar"
            hidden={!current && !last && !jobs.error}
          >
            <div className="task-inner">
              <div className="current-task" role="status">
                {jobs.error ? (
                  "任务状态读取失败"
                ) : current || last ? (
                  <TaskProgress job={(current || last)!} />
                ) : (
                  "当前无书写任务"
                )}
              </div>
              <Button kind="ghost" onClick={() => setQueueOpen(true)}>
                队列 {jobs.data?.queued_total || 0}
              </Button>
              <Button
                disabled={!current || stopping}
                onClick={() => current && setCancel(current)}
              >
                中止
              </Button>
            </div>
          </footer>
        </div>
      </div>
      {library && (
        <DocumentLibrary model={doc} close={() => setLibrary(false)} />
      )}
      {queueOpen && (
        <JobQueue
          jobs={jobs.data?.jobs || []}
          total={jobs.data?.queued_total || 0}
          close={() => setQueueOpen(false)}
          cancel={(job) => {
            setQueueOpen(false);
            setCancel(job);
          }}
        />
      )}
      {help && (
        <Dialog
          title="快捷键与帮助"
          confirmLabel="知道了"
          close={() => setHelp(false)}
          confirm={async () => {}}
        >
          <p>
            单击文本框或单元格输入，输入即保存到服务端。Ctrl+Z 撤销，Ctrl+Y
            重做。非文字输入时 Ctrl / ⌘ + A 全选纸面元素，Backspace / Delete
            删除，Esc 取消选择。
          </p>
          <p>
            H 切换小手拖动，Esc 返回选择；Ctrl / ⌘ + 滚轮仅缩放纸张。Shift
            点击可扩展单元格选区。
          </p>
          <p>
            纸张左上角为 0, 0
            mm。虚线和选择框不落笔；勾选“实际书写表格线”后才书写表格框线，默认开启。
          </p>
        </Dialog>
      )}
      {cancel && (
        <Dialog
          title={cancel.status === "queued" ? "取消排队任务" : "中止书写任务"}
          confirmLabel={
            cancel.status === "queued" ? "确认取消排队" : "确认中止"
          }
          close={() => setCancel(undefined)}
          confirm={async () => {
            setStopRequested(cancel.job_id);
            try {
              await api(`/api/v1/jobs/${cancel.job_id}/cancel`, {});
              notify(
                cancel.status === "queued"
                  ? "已取消排队任务"
                  : "已请求停止书写，正在等待抬笔收尾",
              );
              jobs.reload();
            } catch (error) {
              setStopRequested(undefined);
              throw error;
            }
          }}
        >
          {cancel.status === "queued"
            ? `取消任务 #${cancel.job_id} 的排队，不影响正在运行的任务。`
            : "停止发送后续指令，已发送到机器缓冲区的动作可能继续数秒。重新书写会创建新任务。"}
        </Dialog>
      )}
      {toast && (
        <div
          className={`toast ${toast.error ? "error" : ""}`}
          role={toast.error ? "alert" : "status"}
        >
          {toast.text}
          <Button
            kind="ghost"
            onClick={() => setToast(undefined)}
            aria-label="关闭消息"
          >
            ×
          </Button>
        </div>
      )}
    </>
  );
}
