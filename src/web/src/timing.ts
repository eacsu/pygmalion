export function formatDuration(seconds: number) {
  const whole = Math.max(0, Math.ceil(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const rest = whole % 60;
  return hours
    ? `${hours}小时${minutes}分${rest}秒`
    : minutes
      ? `${minutes}分${String(rest).padStart(2, "0")}秒`
      : `${rest}秒`;
}

export const estimateHelp =
  "按路径、设置速度、抬落笔和停顿粗估；空走采用配置速度，未计入设备加减速、固件限速及通信等待，实际可能更久。";
