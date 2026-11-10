import { randomId } from "./uuid";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { request, ApiError } from "./api";
import { readDocument, type WritingDocument } from "./canvas";

export interface StoredDocument {
  id: string;
  revision: number;
  document: WritingDocument;
  created_at: string;
  updated_at: string;
}
function snapshot(value: WritingDocument) {
  return JSON.stringify(value, (_key, item) =>
    item && typeof item === "object" && !Array.isArray(item)
      ? Object.fromEntries(
          Object.entries(item).sort(([a], [b]) => a.localeCompare(b)),
        )
      : item,
  );
}
type Checkpoint = { id: string; revision: number };
const pointerKey = "pygmalion-server-document";
function checkpoint(): Checkpoint | undefined {
  try {
    return JSON.parse(localStorage.getItem(pointerKey) || "null") || undefined;
  } catch {
    return undefined;
  }
}

const recoveryPrefix = "pygmalion-document-recovery:";
type Recovery = { id: string; revision: number; document: WritingDocument };
function recovery(id: string): Recovery | undefined {
  try {
    const value = JSON.parse(
      sessionStorage.getItem(recoveryPrefix + id) || "null",
    );
    if (
      !value ||
      value.id !== id ||
      !Number.isInteger(value.revision) ||
      value.revision < 1
    )
      return undefined;
    return { ...value, document: readDocument(value.document) };
  } catch {
    return undefined;
  }
}

/** 数据库是正式副本；本地快照仅用于恢复断线草稿，不覆盖并发更新。 */
export function useServerDocument(
  document: WritingDocument,
  receive: (doc: WritingDocument) => void,
) {
  const [state, setState] = useState<{
    id?: string;
    ready: boolean;
    saving: boolean;
    error?: string;
    conflict?: boolean;
    opening?: boolean;
    saved: string;
  }>({ ready: false, saving: false, saved: "" });
  const latest = useRef(document);
  const receiver = useRef(receive);
  useLayoutEffect(() => {
    latest.current = document;
    receiver.current = receive;
  }, [document, receive]);
  const current = useRef<StoredDocument | undefined>(undefined);
  const acknowledged = useRef("");
  const blocked = useRef(false);
  const flight = useRef<Promise<void> | undefined>(undefined);
  const initialized = useRef(false);
  const switching = useRef(false);
  const key = useRef(randomId());

  const persistRecovery = useCallback(() => {
    const value = current.current;
    if (!value) return;
    try {
      readDocument(latest.current);
      if (snapshot(latest.current) === acknowledged.current)
        sessionStorage.removeItem(recoveryPrefix + value.id);
      else
        sessionStorage.setItem(
          recoveryPrefix + value.id,
          JSON.stringify({
            id: value.id,
            revision: blocked.current
              ? (recovery(value.id)?.revision ?? value.revision)
              : value.revision,
            document: latest.current,
          }),
        );
    } catch {
      /* 数据库保存和版本校验不依赖浏览器缓存。 */
    }
  }, []);
  const remember = useCallback(
    (value: StoredDocument, sentSnapshot?: string) => {
      current.current = value;
      acknowledged.current = sentSnapshot ?? snapshot(value.document);
      persistRecovery();
      try {
        localStorage.setItem(
          pointerKey,
          JSON.stringify({
            id: value.id,
            revision: value.revision,
          }),
        );
      } catch {
        /* 缓存不可用不影响服务端保存。 */
      }
      const url = new URL(window.location.href);
      url.searchParams.set("document", value.id);
      window.history.replaceState(null, "", url);
      setState({
        id: value.id,
        ready: true,
        saving: false,
        opening: switching.current,
        saved: acknowledged.current,
      });
    },
    [persistRecovery],
  );
  const adopt = useCallback(
    (value: StoredDocument) => {
      try {
        if (current.current)
          sessionStorage.removeItem(recoveryPrefix + current.current.id);
      } catch {
        /* 可选恢复缓存。 */
      }
      blocked.current = false;
      latest.current = readDocument(value.document);
      remember(value);
      receiver.current(latest.current);
    },
    [remember],
  );

  const flush = useCallback(async () => {
    if (flight.current) await flight.current;
    if (blocked.current)
      throw new Error("文档存在版本冲突，请先另存本页修改或读取服务端版本");
    if (!current.current) throw new Error("服务端文档尚未读取，请重试");
    if (snapshot(latest.current) === acknowledged.current) return;
    const run = async () => {
      setState((old) => ({ ...old, saving: true, error: undefined }));
      try {
        while (
          current.current &&
          snapshot(latest.current) !== acknowledged.current
        ) {
          const doc = readDocument(latest.current);
          const result = await request<StoredDocument>(
            `/api/v1/documents/${current.current.id}`,
            "PUT",
            doc,
            undefined,
            { "If-Match": `"${current.current.revision}"` },
          );
          remember(result, snapshot(doc));
        }
      } catch (error) {
        blocked.current =
          error instanceof ApiError && error.code === "document_changed";
        setState((old) => ({
          ...old,
          saving: false,
          conflict: blocked.current,
          error: error instanceof Error ? error.message : "服务端保存失败",
        }));
        throw error;
      }
    };
    const pending = run();
    flight.current = pending;
    try {
      await pending;
    } finally {
      if (flight.current === pending) flight.current = undefined;
    }
  }, [remember]);

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    void (async () => {
      try {
        const cached = checkpoint();
        const id =
          new URL(window.location.href).searchParams.get("document") ||
          cached?.id;
        if (id) {
          const value = await request<StoredDocument>(
            `/api/v1/documents/${id}`,
          );
          const draft = recovery(id);
          if (draft) {
            latest.current = readDocument(draft.document);
            blocked.current = draft.revision !== value.revision;
            remember(value);
            receiver.current(latest.current);
            if (blocked.current) {
              setState((old) => ({
                ...old,
                conflict: true,
                error:
                  "离线草稿与服务端版本不同，请另存本页修改或读取服务端版本",
              }));
            }
          } else adopt(value);
        } else {
          const value = await request<StoredDocument>(
            "/api/v1/documents",
            "POST",
            readDocument(latest.current),
            undefined,
            { "Idempotency-Key": key.current },
          );
          remember(value, snapshot(latest.current));
        }
      } catch (error) {
        setState((old) => ({
          ...old,
          ready: false,
          error: error instanceof Error ? error.message : "服务端文档读取失败",
        }));
      }
    })();
  }, [adopt, remember]);

  const payload = snapshot(document);
  useEffect(() => {
    if (state.ready && !switching.current) persistRecovery();
    if (
      !state.ready ||
      state.conflict ||
      switching.current ||
      payload === acknowledged.current
    )
      return;
    const timer = window.setTimeout(() => {
      void flush().catch(() => undefined);
    }, 180);
    return () => window.clearTimeout(timer);
  }, [payload, state.ready, state.conflict, flush, persistRecovery]);

  useEffect(() => {
    if (!state.ready) return;
    let disposed = false;
    let reading = false;
    const timer = window.setInterval(() => {
      if (
        reading ||
        flight.current ||
        switching.current ||
        !current.current ||
        blocked.current
      )
        return;
      reading = true;
      const id = current.current.id;
      void request<StoredDocument>(`/api/v1/documents/${id}`)
        .then((value) => {
          if (
            disposed ||
            current.current?.id !== id ||
            flight.current ||
            switching.current
          )
            return;
          if (value.revision === current.current.revision) return;
          if (snapshot(latest.current) !== acknowledged.current) {
            blocked.current = true;
            setState((old) => ({
              ...old,
              conflict: true,
              error: "文档已被其他客户端修改，请另存本页修改或读取服务端版本",
            }));
          } else adopt(value);
        })
        .catch(() => undefined)
        .finally(() => {
          reading = false;
        });
    }, 1000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [state.ready, adopt]);

  async function create(doc: WritingDocument, copy = false) {
    switching.current = true;
    setState((old) => ({ ...old, opening: true }));
    try {
      if (!copy) await flush();
      else if (flight.current) await flight.current.catch(() => undefined);
      const value = await request<StoredDocument>(
        "/api/v1/documents",
        "POST",
        readDocument(doc),
        undefined,
        { "Idempotency-Key": randomId() },
      );
      adopt(value);
    } finally {
      switching.current = false;
      setState((old) => ({ ...old, opening: false }));
    }
  }
  async function open(id: string) {
    switching.current = true;
    setState((old) => ({ ...old, opening: true }));
    try {
      await flush();
      adopt(await request<StoredDocument>(`/api/v1/documents/${id}`));
    } finally {
      switching.current = false;
      setState((old) => ({ ...old, opening: false }));
    }
  }
  async function reload() {
    if (flight.current) await flight.current.catch(() => undefined);
    const id =
      current.current?.id ||
      checkpoint()?.id ||
      new URL(window.location.href).searchParams.get("document");
    if (id) adopt(await request<StoredDocument>(`/api/v1/documents/${id}`));
    else {
      const value = await request<StoredDocument>(
        "/api/v1/documents",
        "POST",
        readDocument(latest.current),
        undefined,
        { "Idempotency-Key": key.current },
      );
      adopt(value);
    }
  }
  return {
    ...state,
    synced: state.ready && payload === state.saved,
    flush,
    create,
    open,
    reload,
  };
}
