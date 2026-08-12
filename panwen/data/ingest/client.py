import time
import pandas as pd

_last_call_at: float = 0.0

def fetch(func, *args, min_interval: float = 0.3, retries: int = 3, **kwargs) -> pd.DataFrame:
    """带最小间隔节流 + 指数退避重试的 akshare 调用封装。"""
    # Fix 4: retries<=0 时 for 循环不执行、last_err 保持 None,末尾 `raise last_err`
    # 抛 TypeError("exceptions must derive from BaseException")—— 误导性错误。提前拒绝。
    if retries < 1:
        raise ValueError("retries must be >= 1")
    global _last_call_at
    last_err = None
    for attempt in range(retries):
        elapsed = time.monotonic() - _last_call_at
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        try:
            _last_call_at = time.monotonic()
            return func(*args, **kwargs)
        except Exception as e:  # akshare 上游偶发网络/解析错误
            last_err = e
            time.sleep(0.5 * (2 ** attempt))  # 0.5,1,2...
    raise last_err
