"""在线探测 akshare 实际返回的中文列名,人工核对后填入 specs.RENAME_MAP。
用法: python scripts/probe_akshare.py  (需联网,手动运行,非自动测试)"""
import akshare as ak

def main():
    print("== stock_zh_a_hist(adjust=hfq) ==")
    print(list(ak.stock_zh_a_hist(symbol="000001", period="daily",
                                  start_date="20240101", end_date="20240110",
                                  adjust="hfq").columns))
    print("== stock_zh_a_spot_em ==")
    print(list(ak.stock_zh_a_spot_em().columns))
    print("== stock_financial_analysis_indicator ==")
    print(list(ak.stock_financial_analysis_indicator(symbol="000001", start_year="2023").columns))
    # 其余数据源同理打印列名...

if __name__ == "__main__":
    main()
