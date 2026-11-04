import { useEffect, useState } from "react";
import { request } from "./api";
import type { CircuitElement } from "./circuit";
export type CircuitRender = {
  svg: string;
  layout: {
    wires: { id: string; points: { x_mm: number; y_mm: number }[] }[];
    components: {
      id: string;
      x_mm: number;
      y_mm: number;
      width_mm: number;
      height_mm: number;
      pins: Record<string, { x_mm: number; y_mm: number }>;
    }[];
  };
  diagnostics: {
    code: string;
    message: string;
    severity: string;
    details: { target_id?: string };
  }[];
};
export function useCircuitRender(element?: CircuitElement) {
  const payload = element ? JSON.stringify(element) : undefined;
  const [revision, retry] = useState(0);
  const [state, setState] = useState<{
    payload: string;
    data?: CircuitRender;
    error?: string;
  }>();
  useEffect(() => {
    if (!payload) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void request<CircuitRender>(
        "/api/v1/circuits/render",
        "POST",
        JSON.parse(payload),
        controller.signal,
      )
        .then((data) => {
          if (!controller.signal.aborted) setState({ payload, data });
        })
        .catch((error) => {
          if (!controller.signal.aborted)
            setState({
              payload,
              error: error instanceof Error ? error.message : "电路预览失败",
            });
        });
    }, 180);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [payload, revision]);
  return {
    data: state && state.payload === payload ? state.data : undefined,
    error: state && state.payload === payload ? state.error : undefined,
    retry: () => retry((v) => v + 1),
  };
}
