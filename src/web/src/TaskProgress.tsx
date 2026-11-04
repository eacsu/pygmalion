import { useEffect, useState } from "react";
import type { Job } from "./api";
import { statusNames } from "./navigation";
import { formatDuration, estimateHelp } from "./timing";

export function TaskProgress({ job }: { job: Job }) {
  const [now, setNow] = useState(() => Date.now());
  const active = ["printing", "cancelling"].includes(job.status);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active, job.job_id]);
  const started = Date.parse(job.started_at);
  const ended = Date.parse(job.finished_at);
  const elapsed = Number.isFinite(started)
    ? Math.max(0, ((Number.isFinite(ended) ? ended : now) - started) / 1000)
    : 0;
  const percent = Math.max(0, Math.min(100, job.percent));
  const estimate = job.estimated_duration_seconds;
  const validEstimate =
    estimate != null && Number.isFinite(estimate) && estimate >= 0;
  let time = `已用 ${formatDuration(elapsed)}`;
  if (!active && job.status !== "queued") {
    time = `实际用时 ${formatDuration(elapsed)}`;
  } else if (job.dry_run && validEstimate) {
    time += ` · 预计实机约 ${formatDuration(estimate)}`;
  } else if (job.status === "cancelling") {
    time += " · 等待停止确认";
  } else if (validEstimate) {
    time +=
      job.status === "queued"
        ? ` · 预计用时约 ${formatDuration(estimate)}`
        : elapsed < estimate
          ? ` · 预计剩余约 ${formatDuration(estimate - elapsed)}`
          : " · 已超出预估，等待设备完成";
  } else {
    time += " · 预计时间暂不可用";
  }
  return (
    <div className="task-progress">
      <span className="task-progress-title">
        {job.status === "done" ? "书写完成" : statusNames[job.status]} ·{" "}
        {job.title || "当前文档"}
        {job.dry_run ? " · 演练" : ""}
      </span>
      {active && (
        <span className="task-progress-label">
          指令发送进度 {Math.round(percent)}%
          {active && percent >= 100 && job.status !== "cancelling"
            ? " · 等待设备完成"
            : ""}
        </span>
      )}
      {active && (
        <progress aria-label="指令发送进度" max={100} value={percent} />
      )}
      <span className="task-time numeric" aria-live="off" title={estimateHelp}>
        {time}
      </span>
      {!active && job.message && <span>{job.message}</span>}
    </div>
  );
}
