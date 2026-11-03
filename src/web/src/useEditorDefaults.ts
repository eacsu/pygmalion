import { useRef, useState } from "react";
import { request, useResource, type Config } from "./api";
type EditorDefaults = { font_size_mm: number };
export function useEditorDefaults() {
  const resource = useResource<Config<EditorDefaults>>(
    "/api/v1/settings/editor",
  );
  const [saved, setSaved] = useState<Config<EditorDefaults>>();
  const current = saved ?? resource.data;
  const [saving, setSaving] = useState(false);
  const pending = useRef(false);
  const [saveError, setSaveError] = useState<string>();
  async function save(fontSize: number) {
    if (pending.current || !current) return;
    pending.current = true;
    setSaving(true);
    setSaveError(undefined);
    try {
      setSaved(
        await request<Config<EditorDefaults>>(
          "/api/v1/settings/editor",
          "PATCH",
          { font_size_mm: fontSize },
          undefined,
          { "If-Match": current.etag },
        ),
      );
    } catch (error) {
      setSaveError(
        error instanceof Error ? error.message : "默认字号保存失败，请重试",
      );
    } finally {
      pending.current = false;
      setSaving(false);
    }
  }
  return {
    data: current?.values,
    loading: resource.loading,
    loadError: resource.error,
    saveError,
    saving,
    save,
    reload: resource.reload,
  };
}
