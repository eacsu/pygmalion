import { useRef, useState } from "react";
import { useResource } from "./api";
import { Button, Dialog, ResourceState } from "./ui";
import type { useWorkbench } from "./useWorkbench";
import { navigate } from "./navigation";

type Summary = {
  id: string;
  name: string;
  revision: number;
  element_count: number;
  updated_at: string;
};
export function DocumentLibrary({
  model,
  close,
}: {
  model: ReturnType<typeof useWorkbench>;
  close: () => void;
}) {
  const listing = useResource<{ data: Summary[] }>(
    "/api/v1/documents?limit=200",
  );
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<string>();
  const file = useRef<HTMLInputElement>(null);
  return (
    <Dialog
      title="实例文档库"
      close={close}
      confirmLabel="关闭"
      confirm={async () => {}}
    >
      <p className="muted">
        所有访问此实例的客户端共享此文档库。文档保存在服务端数据库，每份文档独立保存。
      </p>
      <ResourceState
        loading={listing.loading}
        error={listing.error}
        retry={listing.reload}
      />
      {error && (
        <p role="alert" className="error-text">
          {error}
        </p>
      )}
      <div className="document-library" aria-label="服务端文档列表">
        {listing.data?.data.map((item) => (
          <div className="document-library-row" key={item.id}>
            <Button
              kind="ghost"
              disabled={opening}
              onClick={async () => {
                setOpening(true);
                try {
                  await model.server.open(item.id);
                  navigate("/" + window.location.search);
                  close();
                } catch (err) {
                  setError(err instanceof Error ? err.message : "打开文档失败");
                } finally {
                  setOpening(false);
                }
              }}
            >
              {item.name || "未命名文档"}
              {item.id === model.server.id ? " · 当前" : ""}
            </Button>
            <small className="muted">
              版本 {item.revision} · {item.element_count} 个元素 ·{" "}
              {new Date(item.updated_at).toLocaleString()}
            </small>
          </div>
        ))}
        {listing.data?.data.length === 0 && <p>暂无文档，可新建或导入文件。</p>}
      </div>
      <p className="muted">
        显示最近 200 份文档。旧的本机文件可导入为新的服务端文档。
      </p>
      <Button disabled={opening} onClick={() => file.current?.click()}>
        导入文件
      </Button>
      <input
        ref={file}
        type="file"
        hidden
        accept=".json,.txt"
        aria-label="导入文档文件"
        onChange={async (event) => {
          const input = event.target.files?.[0];
          event.target.value = "";
          if (input) {
            await model.open(input);
            navigate("/" + window.location.search);
            close();
          }
        }}
      />
    </Dialog>
  );
}
