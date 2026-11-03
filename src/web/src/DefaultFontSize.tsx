import { useCallback, useState } from "react";
import { NumberField, NumberFieldsProvider } from "./NumberField";
import { Button, ResourceState } from "./ui";
import type { useEditorDefaults } from "./useEditorDefaults";

type Defaults = ReturnType<typeof useEditorDefaults>;

export function DefaultFontSize({
  defaults,
  expanded,
}: {
  defaults: Defaults;
  expanded: boolean;
}) {
  return (
    <details className="editor-defaults" open={expanded}>
      <summary>
        默认字号{" "}
        <span className="muted">
          新建元素{defaults.data ? ` · ${defaults.data.font_size_mm} mm` : ""}
        </span>
      </summary>
      <p className="muted">
        应用于之后新建的文本框和表格，已有元素保留各自字号。
      </p>
      <ResourceState
        loading={defaults.loading}
        error={defaults.loadError}
        retry={defaults.reload}
      />
      {defaults.data && (
        <DefaultFontSizeForm
          key={defaults.data.font_size_mm}
          defaults={defaults}
          value={defaults.data.font_size_mm}
        />
      )}
    </details>
  );
}

function DefaultFontSizeForm({
  defaults,
  value,
}: {
  defaults: Defaults;
  value: number;
}) {
  const [size, setSize] = useState(value);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const report = useCallback(
    (id: string, error?: string) =>
      setErrors((previous) => {
        const next = { ...previous };
        if (error) next[id] = error;
        else delete next[id];
        return next;
      }),
    [],
  );
  return (
    <NumberFieldsProvider report={report}>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!Object.keys(errors).length) void defaults.save(size);
        }}
      >
        <fieldset disabled={defaults.saving}>
          <NumberField
            label="默认字号"
            value={size}
            min={4}
            max={40}
            change={setSize}
          />
          <Button
            type="submit"
            disabled={
              defaults.saving || !!Object.keys(errors).length || size === value
            }
          >
            {defaults.saving ? "正在保存…" : "保存默认字号"}
          </Button>
        </fieldset>
        {defaults.saveError && <p role="alert">{defaults.saveError}</p>}
      </form>
    </NumberFieldsProvider>
  );
}
