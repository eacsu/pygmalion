import type { Job } from "./api";
import { Button, Dialog } from "./ui";
import { statusNames } from "./navigation";

export function JobQueue({
  jobs,
  total,
  close,
  cancel,
}: {
  jobs: Job[];
  total: number;
  close: () => void;
  cancel: (job: Job) => void;
}) {
  const active = jobs
    .filter((job) => ["queued", "printing", "cancelling"].includes(job.status))
    .sort((a, b) => a.job_id - b.job_id);
  return (
    <Dialog
      title="实例任务队列"
      close={close}
      confirmLabel="关闭"
      confirm={async () => {}}
    >
      <p>等待 {total} 个任务。所有客户端提交到同一队列，机器按顺序逐个执行。</p>
      <div className="document-library" aria-label="公共任务队列">
        {active.map((job) => (
          <div key={job.job_id} className="queue-row">
            <div>
              <strong>
                #{job.job_id} · {job.title || "未命名文档"}
              </strong>
              <p className="muted">
                {statusNames[job.status]} · {job.dry_run ? "模拟" : "真实书写"}{" "}
                · 内容与参数已冻结
              </p>
            </div>
            <Button
              disabled={job.status === "cancelling"}
              onClick={() => cancel(job)}
            >
              {job.status === "queued" ? "取消排队" : "停止书写"}
            </Button>
          </div>
        ))}
        {!active.length && <p>当前没有运行或排队的任务。</p>}
      </div>
      {total > 200 && <p className="muted">仅显示最前面的 200 个等待任务。</p>}
      <p className="muted">
        服务重启后保留任务记录；不会自动续写未完成的实体任务。
      </p>
    </Dialog>
  );
}
