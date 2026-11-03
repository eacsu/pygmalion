import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  submitPlan,
  hasPendingSubmission,
  type Mode,
  type Job,
} from "./api";
import { usePaperPreview } from "./usePaperPreview";
import { useServerDocument } from "./useServerDocument";
import { useEditorDefaults } from "./useEditorDefaults";

import {
  blank,
  newVector,
  type VectorElement,
  readDocument,
  type WritingDocument,
  type PaperElement,
  type Table,
  type Diagnostic,
} from "./canvas";
export type { WritingDocument } from "./canvas";
const storageKey = "pygmalion-document-v2";
function initialDocument() {
  try {
    const saved =
      localStorage.getItem(storageKey) ||
      localStorage.getItem("pygmalion-document-v1");
    return saved ? readDocument(JSON.parse(saved)) : structuredClone(blank);
  } catch {
    return structuredClone(blank);
  }
}
type Props = {
  busy: boolean;
  mode: Mode;
  jobs?: Job[];
  notify: (text: string, error?: boolean) => void;
  refresh: () => void;
};
export function useWorkbench({ mode, jobs, notify, refresh }: Props) {
  const defaults = useEditorDefaults();
  const [document, setDocument] = useState(initialDocument);
  // 服务端文档负责正式保存；浏览器缓存仅用于迁移和恢复。
  const [inputEpoch, setInputEpoch] = useState(0);
  const [inputErrors, setInputErrors] = useState<Record<string, string>>({});
  const inputErrorsRef = useRef<Record<string, string>>({});
  const reportInput = useCallback((id: string, error?: string) => {
    if (inputErrorsRef.current[id] === error) return;
    const next = { ...inputErrorsRef.current };
    if (error) next[id] = error;
    else delete next[id];
    inputErrorsRef.current = next;
    setInputErrors(next);
  }, []);
  function resetInputs(restoreFocus = false) {
    const active = window.document.activeElement;
    const label =
      restoreFocus && active?.matches("input[data-number-field]")
        ? active.getAttribute("aria-label")
        : undefined;
    inputErrorsRef.current = {};
    setInputErrors({});
    setInputEpoch((v) => v + 1);
    if (label)
      requestAnimationFrame(() => {
        window.document
          .querySelector<HTMLInputElement>(
            `input[data-number-field][aria-label="${CSS.escape(label)}"]`,
          )
          ?.focus();
      });
  }
  function invalidInput() {
    const message = Object.values(inputErrorsRef.current)[0];
    if (message) notify(message, true);
    return !!message;
  }
  const latest = useRef(document);
  const cachedRef = useRef("");
  const history = useRef<{
    past: WritingDocument[];
    future: WritingDocument[];
    editing?: { key: string; baseline: WritingDocument };
  }>({ past: [], future: [] });
  const [historyState, setHistoryState] = useState({
    canUndo: false,
    canRedo: false,
  });
  function refreshHistory() {
    const state = history.current;
    setHistoryState({
      canUndo:
        !!state.past.length ||
        !!(
          state.editing &&
          JSON.stringify(state.editing.baseline) !==
            JSON.stringify(latest.current)
        ),
      canRedo: !!state.future.length,
    });
  }
  const [composing, setComposing] = useState(false);
  const persist = useCallback((next: WritingDocument) => {
    try {
      // 不能用无法重新打开的文档覆盖上一份可恢复草稿。
      readDocument(next);
      const snapshot = JSON.stringify(next);
      localStorage.setItem(storageKey, snapshot);
      cachedRef.current = snapshot;
      return true;
    } catch {
      return false;
    }
  }, []);
  const migrationNotified = useRef(false);
  useEffect(() => {
    if (migrationNotified.current) return;
    migrationNotified.current = true;
    try {
      if (!localStorage.getItem(storageKey)) {
        const old = localStorage.getItem("pygmalion-document-v1");
        if (old && JSON.parse(old).direction === "vertical")
          notify("旧竖排文档已转换为横排，请检查纸面后保存");
      }
    } catch {
      /* 无效旧文档由加载器恢复为空白文档。 */
    }
  }, [notify]);
  useEffect(() => {
    persist(latest.current);
  }, [persist]);
  const [revision, setRevision] = useState(0);
  const [generation, setGeneration] = useState(0);
  const [writing, setWriting] = useState(false);
  const [jobId, setJobId] = useState<number>();
  const posting = useRef(false);
  const [pendingSubmission, setPendingSubmission] = useState(() =>
    hasPendingSubmission(),
  );
  const server = useServerDocument(document, (next) => {
    history.current = { past: [], future: [] };
    latest.current = next;
    persist(next);
    setDocument(next);
    setGeneration((value) => value + 1);
    resetInputs();
    refreshHistory();
  });
  useEffect(() => {
    queueMicrotask(() => setPendingSubmission(hasPendingSubmission(server.id)));
  }, [server.id]);
  const dirty = !server.synced;
  const locked = !server.ready || !!server.opening || writing;
  const { preview, error, previewUrl } = usePaperPreview(
    document,
    generation,
    revision,
  );
  useEffect(() => {
    if (writing && jobId && jobs?.some((job) => job.job_id === jobId))
      queueMicrotask(() => setWriting(false));
  }, [jobs, jobId, writing]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (!server.synced) event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [server.synced]);
  const lockedRef = useRef(locked);
  useEffect(() => {
    lockedRef.current = locked;
  }, [locked]);
  const [fitting, setFitting] = useState(false);
  function endEdit(key?: string) {
    const group = history.current.editing;
    if (!group || (key !== undefined && group.key !== key)) return;
    history.current.editing = undefined;
    if (JSON.stringify(group.baseline) !== JSON.stringify(latest.current)) {
      history.current.past = [
        ...history.current.past.slice(-49),
        group.baseline,
      ];
    }
    refreshHistory();
  }
  function beginEdit(key: string) {
    if (locked || lockedRef.current || history.current.editing?.key === key)
      return;
    endEdit();
    history.current.editing = { key, baseline: latest.current };
    refreshHistory();
  }
  function apply(next: WritingDocument) {
    // 不在 React updater/effect 中写存储：输入事件返回前就持久化最新正文。
    latest.current = next;
    persist(next);
    setDocument(next);
    refreshHistory();
  }
  function commit(next: WritingDocument) {
    if (locked || lockedRef.current) return;
    if (JSON.stringify(next) === JSON.stringify(latest.current)) {
      if (JSON.stringify(next) !== cachedRef.current) persist(next);
      return;
    }
    if (!history.current.editing)
      history.current.past = [
        ...history.current.past.slice(-49),
        latest.current,
      ];
    history.current.future = [];
    apply(next);
  }
  function replaceElement(element: PaperElement) {
    commit({
      ...latest.current,
      elements: latest.current.elements.map((e) =>
        e.id === element.id ? element : e,
      ),
    });
  }
  function replaceText(id: string, text: string, row?: number, col?: number) {
    const element = latest.current.elements.find((item) => item.id === id);
    if (!element || element.type === "vector") return;
    replaceElement(
      element.type === "text"
        ? { ...element, text }
        : {
            ...element,
            cells: element.cells.map((cell) =>
              cell.row === row && cell.col === col ? { ...cell, text } : cell,
            ),
          },
    );
  }
  function travel(direction: "undo" | "redo") {
    if (locked || lockedRef.current) return;
    resetInputs(true);
    const key = history.current.editing?.key;
    endEdit();
    const state = history.current;
    const next = direction === "undo" ? state.past.pop() : state.future.shift();
    if (next) {
      if (direction === "undo") state.future.unshift(latest.current);
      else state.past = [...state.past.slice(-49), latest.current];
      apply(next);
    }
    // 保持输入焦点；后续输入从恢复后的正文开始新的一次编辑。
    if (key !== undefined) state.editing = { key, baseline: latest.current };
    refreshHistory();
  }
  function undo() {
    travel("undo");
  }
  function redo() {
    travel("redo");
  }
  async function fit(id: string) {
    if (locked || fitting || invalidInput()) return;
    const snapshot = JSON.stringify(document);
    setFitting(true);
    try {
      const result = await api<{
        element: Table;
        diagnostics: Diagnostic[];
        success: boolean;
      }>("/api/v1/documents/fit-table", { document, element_id: id });
      if (
        lockedRef.current ||
        Object.keys(inputErrorsRef.current).length ||
        JSON.stringify(latest.current) !== snapshot
      ) {
        notify("文档已变化，请重新自适应", true);
        return;
      }
      if (result.diagnostics.length) {
        notify(result.diagnostics.map((d) => d.message).join("；"), true);
        return;
      }
      replaceElement(result.element);
      notify("表格已自适应，外框尺寸保持不变");
    } catch (e) {
      notify(e instanceof Error ? e.message : "自适应失败", true);
    } finally {
      setFitting(false);
    }
  }
  function change<K extends keyof WritingDocument>(
    key: K,
    value: WritingDocument[K],
  ) {
    if (!locked) {
      const next = { ...latest.current, [key]: value };
      commit(next);
    }
  }
  async function newDocument() {
    if (locked) return;
    try {
      await server.create(structuredClone(blank));
    } catch (error) {
      notify(error instanceof Error ? error.message : "新建失败", true);
    }
  }
  async function save() {
    if (invalidInput()) return;
    try {
      endEdit();
      const current = latest.current;
      const payload = JSON.stringify(current);
      readDocument(current);
      persist(current);
      let synced = true;
      try {
        await server.flush();
      } catch {
        synced = false;
      }
      const url = URL.createObjectURL(
        new Blob([payload], { type: "application/json" }),
      );
      const link = window.document.createElement("a");
      link.href = url;
      link.download =
        (current.name.replace(/[\\/:*?"<>|]/g, "_") || "未命名文档") +
        ".pygmalion.json";
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      notify(
        synced
          ? "文档已保存到服务端，并导出副本"
          : "文件已导出；服务端保存失败，请重试",
        !synced,
      );
    } catch (e) {
      notify(e instanceof Error ? e.message : "保存失败，请重试", true);
    }
  }
  async function open(input: File) {
    const baseline = latest.current;
    try {
      if (input.size > 4_000_000) throw new Error("文档文件过大");
      const text = await input.text();
      if (input.name.toLowerCase().endsWith(".txt") && !defaults.data)
        throw new Error("默认字号尚未读取，请读取成功后再导入文本");
      const next = input.name.toLowerCase().endsWith(".txt")
        ? readDocument({
            name: input.name.replace(/\.txt$/i, ""),
            paper: "A4",
            margin_mm: 20,
            body: text,
            font_size_mm: defaults.data?.font_size_mm,
          })
        : readDocument(JSON.parse(text));
      if (next.elements.some((e) => e.type === "vector"))
        await api("/api/v1/documents/validate", next);
      if (latest.current !== baseline)
        throw new Error("文档已变化，请重新打开文件");
      if (lockedRef.current) {
        notify("书写中无法打开文档", true);
        return;
      }
      await server.create(next);
      notify(
        "文档已打开" +
          (!input.name.toLowerCase().endsWith(".txt") &&
          JSON.parse(text).direction === "vertical"
            ? "；旧竖排内容已转换为横排"
            : ""),
      );
    } catch (e) {
      notify(e instanceof Error ? e.message : "无法打开文档", true);
    }
  }
  const [importing, setImporting] = useState(false);
  const importPending = useRef(false);
  async function importSvg(input: File): Promise<string | undefined> {
    if (lockedRef.current || importPending.current) return;
    const baseline = latest.current;
    importPending.current = true;
    setImporting(true);
    try {
      if (input.size > 1_000_000) throw new Error("SVG 文件不能超过 1 MB");
      const { element: result } = await api<{ element: VectorElement }>(
        "/api/v1/imports/svg",
        {
          source: await input.text(),
          name: input.name.replace(/\.svg$/i, "").slice(0, 120),
        },
      );
      if (lockedRef.current || latest.current !== baseline)
        throw new Error("文档已变化，请重新导入 SVG");
      if (latest.current.elements.length >= 100)
        throw new Error("纸面最多支持 100 个元素");
      const vector = newVector(latest.current, result);
      const next = {
        ...latest.current,
        elements: [...latest.current.elements, vector],
      };
      readDocument(next);
      endEdit();
      commit(next);
      notify(
        result.draw_mode === "solid"
          ? "SVG 已导入：实心填充绘制"
          : "SVG 已导入：轮廓绘制",
      );
      return vector.id;
    } catch (error) {
      notify(error instanceof Error ? error.message : "SVG 导入失败", true);
    } finally {
      importPending.current = false;
      setImporting(false);
    }
  }
  const canWrite = pendingSubmission
    ? !locked
    : !!document.elements.length &&
      !!preview?.can_print &&
      !preview.overflow &&
      !preview.missing.length &&
      !error &&
      !locked &&
      !fitting &&
      !Object.keys(inputErrors).length &&
      !composing;
  async function write() {
    if (
      (!pendingSubmission && !canWrite) ||
      posting.current ||
      (!pendingSubmission && invalidInput())
    )
      return;
    posting.current = true;
    setWriting(true);
    try {
      await server.flush();
      const result = await submitPlan(preview?.plan_id || "", mode, server.id);
      setJobId(result.id);
      refresh();
      notify(
        pendingSubmission
          ? `已找回任务 #${result.id}，请查看任务状态`
          : result.mode === "simulate"
            ? "演练任务已入队，内容与参数已冻结"
            : "书写任务已入队，内容与参数已冻结",
      );
    } catch (e) {
      setWriting(false);
      notify(e instanceof Error ? e.message : "书写失败", true);
    } finally {
      setPendingSubmission(hasPendingSubmission(server.id));
      posting.current = false;
    }
  }
  return {
    defaults,
    document,
    importSvg,
    importing,
    change,
    commit,
    replaceElement,
    undo,
    redo,
    canUndo: historyState.canUndo,
    canRedo: historyState.canRedo,
    beginEdit,
    endEdit,
    replaceText,
    composing,
    setComposing,
    saveError: server.error,
    server,
    inputEpoch,
    inputErrors,
    reportInput,
    locallySaved: server.synced,
    retrySave: () =>
      void (server.ready ? server.flush() : server.reload()).catch((error) =>
        notify(error.message, true),
      ),
    fit,
    fitting,
    notify,
    locked,
    dirty,
    preview,
    previewUrl,
    error,
    canWrite,
    writing,
    jobId,
    pendingSubmission,
    newDocument,
    save,
    open,
    write,
    reload: () => {
      setRevision((v) => v + 1);
    },
  };
}
