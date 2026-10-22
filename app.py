"""Run with: .venv/bin/python -m streamlit run app.py"""
from dataclasses import asdict
from datetime import date, datetime, timedelta
import io
import json
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from quantlab.backtest import BacktestConfig, evaluate_splits, run_backtest
from quantlab.config import DATA, ROOT, SHANGHAI, api_config, is_cloud
from quantlab.data import AKShareProvider, DataError, cache_directory, load_cached, load_example, market_status
from quantlab.deepseek_client import AIError, DeepSeekClient, redact
from quantlab.market_rules import FeeConfig, validate_symbol
from quantlab.storage import Store
from quantlab.strategies import StrategySpec, indicators, targets

st.set_page_config(page_title="DeepSeek Quant Lab", page_icon="📈", layout="wide")
if is_cloud():
    from quantlab.cloud_access import cloud_store
    store, owner_mode = cloud_store()
else:
    store, owner_mode = Store(), True
if "dataset" not in st.session_state:
    st.session_state.dataset = load_example()
if "chat" not in st.session_state:
    st.session_state.chat = []

st.markdown("""<style>
.block-container{padding-top:2rem;max-width:1500px} [data-testid=stMetric]{background:#141f33;
padding:16px;border:1px solid #243650;border-radius:10px} h1{letter-spacing:-1px}
</style>""", unsafe_allow_html=True)
st.sidebar.title("📈 DeepSeek Quant Lab")
st.sidebar.caption(("云端" if is_cloud() else "本地") + "量化研究工作台 · Phase 1")
page = st.sidebar.radio("工作空间", ["仪表盘", "股票行情", "AI 策略研究", "策略回测", "模拟交易", "策略实验室", "系统设置"])
st.sidebar.divider()
st.sidebar.caption("研究回测已启用 · 实盘完全禁用")
st.sidebar.caption("全部行情时间：Asia/Shanghai")
data = st.session_state.dataset
df, meta = data.frame, data.meta
st.title(page)
if meta["sample"]:
    st.warning("当前使用【人工合成测试数据】，代码 000001 仅用于校验费率；所有价格、日期和收益均不代表平安银行真实行情。")
else:
    st.info(f"{meta['symbol']} · {meta['label']} · 数据截至 {meta['last_bar']} · 下载时间 {meta['fetched_at']}")
fee_cfg = FeeConfig(**store.setting("fees", {}))


def chart(frame):
    x = indicators(frame)
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=.035,
                        row_heights=[.52, .17, .16, .15])
    fig.add_trace(go.Candlestick(x=x.date, open=x.open, high=x.high, low=x.low, close=x.close,
                                name="日K", increasing_line_color="#ef5350", decreasing_line_color="#26a69a"), row=1, col=1)
    for n in (5, 10, 20, 60):
        fig.add_trace(go.Scatter(x=x.date, y=x[f"MA{n}"], name=f"MA{n}", line={"width": 1}), row=1, col=1)
    fig.add_trace(go.Bar(x=x.date, y=x.volume, name="成交量/股", marker_color="#3b82f6"), row=2, col=1)
    for col in ("DIF", "DEA", "MACD"):
        fig.add_trace(go.Scatter(x=x.date, y=x[col], name=col), row=3, col=1)
    fig.add_trace(go.Scatter(x=x.date, y=x.RSI14, name="RSI14"), row=4, col=1)
    fig.update_layout(height=760, template="plotly_dark", xaxis_rangeslider_visible=False,
                      margin={"l": 10, "r": 10, "t": 15, "b": 10}, legend={"orientation": "h"})
    st.plotly_chart(fig, width="stretch")


def pct(value):
    return "—" if value is None else f"{value:.2%}"


def show_result(result, benchmark=None):
    m = result.metrics
    cols = st.columns(4)
    for col, name, val in zip(cols, ["总收益率", "年化收益率", "最大回撤", "胜率（已平仓）"],
                              [m["total_return"], m["annual_return"], m["max_drawdown"], m["win_rate"]]):
        col.metric(name, pct(val))
    cols = st.columns(4)
    cols[0].metric("买卖成交笔数 / 完整往返", f"{m['trade_count']} / {m['closed_trades']}")
    cols[1].metric("盈亏比", "—" if m["payoff_ratio"] is None else f"{m['payoff_ratio']:.2f}")
    cols[2].metric("夏普（无风险利率0）", "—" if m["sharpe"] is None else f"{m['sharpe']:.2f}")
    cols[3].metric("手续费 / 滑点成本", f"¥{m['total_fees']:.2f} / ¥{m['slippage_cost']:.2f}")
    fig = go.Figure(go.Scatter(x=result.curve.date, y=result.curve.equity, name="策略净资产"))
    if benchmark is not None:
        fig.add_trace(go.Scatter(x=benchmark.curve.date, y=benchmark.curve.equity, name="同仓位买入持有（含费用）"))
        st.caption(f"买入持有收益 {pct(benchmark.metrics['total_return'])}；同资金、同费率、次日开盘买入；期末按市价计值，不强制清仓。")
    fig.update_layout(template="plotly_dark", height=380)
    st.plotly_chart(fig, width="stretch")
    st.caption("年化按实际自然日折算，短区间会放大；夏普按252日；胜率及盈亏比只统计已平仓交易。期末持仓未扣未来卖出费。")
    a, b = st.tabs(["逐笔成交", "未成交及原因"])
    with a:
        st.dataframe(pd.json_normalize(result.trades), width="stretch")
        st.download_button("导出成交 CSV", pd.json_normalize(result.trades).to_csv(index=False).encode("utf-8-sig"), "trades.csv")
    with b:
        st.dataframe(result.rejections, width="stretch")


if page == "仪表盘":
    a, b, c = st.columns(3)
    a.metric("历史日线", f"{len(df)} 根")
    b.metric("已保存实验", len(store.rows("experiments", 100000)))
    c.metric("DeepSeek", "已填写 Key，待测试" if api_config()["key"] else "未配置 Key")
    st.write(market_status())
    st.subheader("研究路径")
    st.write("股票行情 → AI 策略研究 → 人工选择确定性参数 → 策略回测 → 分段验证 → 保存实验 → AI 复盘")
    st.caption("第一阶段：历史研究可用；独立模拟账户、自动研究循环和实盘接口准备属于后续阶段。")
    chart(df.tail(180))

elif page == "股票行情":
    st.caption("可按六位代码查询沪深普通主板。名称搜索是内置小型示例目录，不是全市场证券主表。")
    names = {"000001": "平安银行", "000002": "万科A", "600000": "浦发银行", "600036": "招商银行", "600519": "贵州茅台"}
    search = st.text_input("名称或代码搜索", "000001")
    matches = [f"{code} {name}" for code, name in names.items() if search in code or search in name]
    if matches:
        selected = st.selectbox("目录匹配", matches).split()[0]
    else:
        selected = search.strip()
    with st.form("history"):
        code = st.text_input("股票代码（可直接输入）", selected)
        source = st.selectbox("历史数据源", ["tencent", "eastmoney"], format_func=lambda x: {"tencent": "AKShare / 腾讯 · 历史日线", "eastmoney": "AKShare / 东方财富 · 历史日线"}[x])
        left, right = st.columns(2)
        start_date = left.date_input("开始日期", datetime.now(SHANGHAI).date() - timedelta(days=730), min_value=date(2015, 8, 3))
        end_date = right.date_input("结束日期", datetime.now(SHANGHAI).date())
        fetch = st.form_submit_button("获取真实历史日线", type="primary")
    if fetch:
        try:
            with st.spinner("访问公开历史源，最多两次请求；不会用假数据替代失败结果…"):
                st.session_state.dataset = AKShareProvider(source).history(code, start_date, end_date)
                st.session_state.pop("backtest", None)
            store.audit("history_download", st.session_state.dataset.meta)
            st.rerun()
        except (DataError, ValueError) as exc:
            store.audit("history_download_failed", {"symbol": code, "source": source, "error_class": type(exc).__name__})
            st.error(str(exc))
    if st.button("载入人工合成离线示例"):
        st.session_state.dataset = load_example()
        st.session_state.pop("backtest", None)
        st.rerun()
    cached = sorted(cache_directory().glob("??????_*_????-??-??_????-??-??.csv"))
    if cached:
        with st.expander("断网时载入已下载的真实历史缓存"):
            cached_choice = st.selectbox("缓存文件", cached, format_func=lambda x: x.stem)
            if st.button("载入所选历史缓存"):
                try:
                    st.session_state.dataset = load_cached(cached_choice)
                    st.session_state.pop("backtest", None)
                    st.rerun()
                except (DataError, ValueError, OSError):
                    st.error("缓存文件损坏或不可读，请重新获取")
    st.subheader("当前数据")
    last = df.iloc[-1]
    a, b, c, d = st.columns(4)
    a.metric("最近历史收盘价", f"¥{last.close:.2f}")
    b.metric("该交易日涨跌幅", pct(last.close / df.close.iloc[-2] - 1) if len(df) > 1 else "—")
    c.metric("成交量（股）", f"{last.volume:,.0f}")
    d.metric("成交额（元）", f"{last.amount:,.0f}" if "amount" in df else "源站未提供")
    st.caption(f"最后交易日 {meta['last_bar']}；日线收盘观察，不是当前最新成交报价。")
    chart(df)
    st.dataframe(indicators(df).tail(30), width="stretch")
    st.json(meta, expanded=False)
    st.download_button("导出当前日线 CSV", df.to_csv(index=False).encode("utf-8-sig"), "historical_bars.csv")
    if st.button("加入自选", disabled=meta["sample"]):
        store.watch(meta["symbol"], names.get(meta["symbol"], "用户查询股票"))
        st.success("已保存到本地自选股")
    for item in store.rows("watchlist"):
        left, right = st.columns([5, 1])
        left.write(f"{item['symbol']} {item['name']}")
        if right.button("移除", key=item["symbol"]):
            store.watch(item["symbol"], item["name"], remove=True)
            st.rerun()

elif page == "策略回测":
    st.warning("研究范围：普通、成熟、非 ST 主板股票。日线无法核实历史 ST/IPO 状态、逐笔成交队列和完整公司行动；结果仅是价格策略探索，不是含分红的总回报。请先核实所选区间无除权除息，勿据此自动交易。")
    proposed = st.session_state.get("adopted_spec", StrategySpec().model_dump())
    with st.form("backtest_params"):
        kind = st.selectbox("策略", ["ma_cross", "volume_breakout"], index=0 if proposed["kind"] == "ma_cross" else 1,
                            format_func=lambda x: {"ma_cross": "A · 双均线交叉", "volume_breakout": "B · 成交量突破"}[x])
        a, b, c = st.columns(3)
        short = a.number_input("短期均线", 2, 120, proposed["short"])
        long = b.number_input("长期均线", 3, 250, proposed["long"])
        lookback = c.number_input("突破及量能回看天数 N", 3, 120, proposed["lookback"])
        a, b, c = st.columns(3)
        multiple = a.number_input("放量倍数", 1.0, 10.0, float(proposed["volume_multiple"]), step=.1)
        exit_ma = b.number_input("突破策略退出均线", 2, 120, proposed["exit_ma"])
        capital = c.number_input("初始资金（元）", min_value=1000.0, value=10000.0, step=1000.0)
        a, b, c = st.columns(3)
        allocation = a.slider("目标买入资金比例", .1, 1.0, .95, .05)
        first = b.date_input("评估开始", df.date.iloc[0].date(), key="btstart")
        last = c.date_input("评估结束", df.date.iloc[-1].date(), key="btend")
        acknowledged = st.checkbox("我确认证券及区间适用上述研究假设；合成数据只用于功能演示", value=bool(meta["sample"]))
        submit = st.form_submit_button("运行回测与分段验证", type="primary")
    st.caption("均线交叉：上穿买入、下穿卖出；突破：收盘突破过去N日最高价且量能放大，收盘跌破退出均线时卖出。所有信号最早下一日开盘成交。")
    if submit:
        try:
            if not acknowledged:
                raise ValueError("请先核实证券类别及公司行动区间，再确认研究假设")
            if first >= last:
                raise ValueError("结束日期必须晚于开始日期")
            spec = StrategySpec(kind=kind, short=short, long=long, lookback=lookback, volume_multiple=multiple, exit_ma=exit_ma)
            cfg = BacktestConfig(symbol=meta["symbol"], initial_cash=capital, allocation=allocation)
            result = run_backtest(df, spec, cfg, fee_cfg, first, last)
            benchmark = run_backtest(df, spec, cfg, fee_cfg, first, last, buy_hold=True)
            subset = df[(df.date >= pd.Timestamp(first)) & (df.date <= pd.Timestamp(last))].reset_index(drop=True)
            splits = evaluate_splits(subset, spec, cfg, fee_cfg) if len(subset) >= 100 else []
            config = {"strategy": spec.model_dump(), "account": asdict(cfg), "fees": asdict(fee_cfg),
                      "data": meta, "start": str(first), "end": str(last), "splits": splits,
                      "benchmark": benchmark.metrics, "assumptions_acknowledged": True}
            st.session_state.backtest = (result, benchmark, config, data.fingerprint)
            store.audit("backtest_completed", {"symbol": meta["symbol"], "strategy": spec.model_dump(), "fingerprint": data.fingerprint})
        except (ValueError, DataError) as exc:
            store.audit("backtest_rejected", {"symbol": meta["symbol"], "error_class": type(exc).__name__})
            st.error(str(exc))
    if "backtest" in st.session_state:
        result, benchmark, config, fingerprint = st.session_state.backtest
        show_result(result, benchmark)
        if config["splits"]:
            st.subheader("固定参数的时间顺序分段检验")
            st.dataframe(config["splits"], width="stretch")
            st.caption("60%训练 / 20%验证 / 20%样本外，各区间重新从现金开始，可使用过去行情预热；未自动选参。反复查看样本外后调参，该区间便不再是真正未见样本。滚动调参验证在第三阶段。")
        label = st.text_input("实验名称", f"{config['strategy']['kind']} · {meta['symbol']}")
        if st.button("保存为新实验版本"):
            exp_id = store.save_experiment(label[:120], config, result, fingerprint)
            st.success(f"已保存实验 #{exp_id}，旧版本保留")

elif page == "AI 策略研究":
    if is_cloud() and not owner_mode:
        st.info("请展开左侧“站主登录”后使用 AI。访客仍可查看历史行情、运行回测和导出本次会话实验。")
        st.stop()
    st.caption("真实调用 DeepSeek 官方 API。只发送当前历史数据摘要、你选中的研究结果和本页对话；不要输入证券账户、密码或个人敏感信息。AI 不接触订单接口。")
    cfg = api_config()
    if not cfg["key"]:
        st.info("请在托管平台 Secrets 中配置 DEEPSEEK_API_KEY，再到系统设置测试连接。" if is_cloud() else "请在根目录 .env 中填写 DEEPSEEK_API_KEY。获取地址：https://platform.deepseek.com/api_keys；保存后去系统设置测试连接。")
    experiments = store.rows("experiments")
    options = {f"#{x['id']} · {x['name']}": x for x in experiments}
    selected = st.selectbox("附加一个已保存回测用于复盘", ["不附加", *options])
    context = {"data_provenance": meta, "recent_daily_bars": df.tail(30).assign(date=lambda x: x.date.astype(str)).to_dict("records"),
               "limitations": "不复权价格；公司行动和历史证券状态不完整；无实时数据；单股票选择存在幸存者偏差"}
    if selected != "不附加":
        x = options[selected]
        context["experiment"] = {"id": x["id"], "config": json.loads(x["config"]), "metrics": json.loads(x["metrics"])}
    with st.expander("检查本次要发送的数据摘要"):
        st.json(context)
    for item in st.session_state.chat:
        with st.chat_message(item["role"]):
            st.write(item["content"])
    question = st.chat_input("讨论行情特征、研究假设或回测结果（会产生 API 费用）")
    if question:
        clean = redact(question, cfg["key"])
        try:
            with st.spinner("请求 DeepSeek，并严格校验结构化 JSON…"):
                reply = DeepSeekClient(store).research(clean, context, st.session_state.chat)
            st.session_state.chat.extend([{"role": "user", "content": clean},
                {"role": "assistant", "content": json.dumps(reply.model_dump(), ensure_ascii=False)}])
            st.session_state.ai_reply = reply.model_dump()
            st.rerun()
        except AIError as exc:
            st.error(str(exc))
    if "ai_reply" in st.session_state:
        reply = st.session_state.ai_reply
        st.subheader(reply["strategy_name"])
        st.write(reply["analysis"])
        for field, title in [("trading_conditions", "交易条件"), ("exit_rules", "退出规则"), ("hypotheses", "待验证假设"), ("risks", "风险")]:
            with st.expander(title, expanded=True):
                for item in reply[field]:
                    st.write("• " + item)
        st.json(reply["strategy"])
        st.caption("执行只识别上面允许的模板参数；自然语言附加条件不执行。人工采用后仍须在回测页确认。")
        if st.button("人工采用参数，供回测页选择"):
            st.session_state.adopted_spec = reply["strategy"]
            store.audit("ai_parameters_manually_adopted", reply["strategy"])
            st.success("已采用参数，打开策略回测页运行；没有修改代码或交易规则")
        st.download_button("导出研究 JSON", json.dumps(reply, ensure_ascii=False, indent=2), "research.json")
    if st.button("清空本页对话"):
        st.session_state.chat = []
        st.rerun()

elif page == "策略实验室":
    rows = store.rows("experiments")
    if not rows:
        st.info("先到策略回测运行并保存一个实验。每次保存都是新版本。")
    else:
        summary = [{"实验ID": x["id"], "名称": x["name"], "保存时间": x["created"],
                    "数据类型": json.loads(x["config"])["data"]["label"], **json.loads(x["metrics"])} for x in rows]
        st.dataframe(summary, width="stretch")
        ids = st.multiselect("比较实验", [x["id"] for x in rows], default=[rows[0]["id"]])
        fig = go.Figure()
        for x in rows:
            if x["id"] in ids:
                curve = pd.read_json(io.StringIO(x["curve"]))
                initial = json.loads(x["config"])["account"]["initial_cash"]
                fig.add_trace(go.Scatter(x=curve.date, y=curve.equity / initial, name=f"#{x['id']} {x['name']}"))
        st.plotly_chart(fig, width="stretch")
        st.caption("曲线按各自初始资金归一化；比较时应保证区间、行情来源和成本一致。")
        for x in rows:
            if x["id"] in ids:
                with st.expander(f"实验 #{x['id']} 配置、分段结果与数据指纹"):
                    st.json({"config": json.loads(x["config"]), "fingerprint": x["fingerprint"]})
                    st.download_button("导出完整实验 JSON", json.dumps(x, ensure_ascii=False, indent=2), f"experiment_{x['id']}.json", key=f"export_{x['id']}")
    with st.expander("已保存的 AI 研究报告"):
        for report in store.rows("reports", 20):
            st.write(f"#{report['id']} · {report['created']}")
            st.json(json.loads(report["content"]), expanded=False)

elif page == "模拟交易":
    st.info("第二阶段待开发：当前没有独立虚拟账户、持仓或模拟订单。历史回测净资产不能视为模拟交易账户。")
    st.error("历史行情 / 合成数据不具备实时交易信号资格，所有模拟和实盘订单入口均关闭。")
    st.write("下一阶段将实现：虚拟账户、逐日持仓、T+1 可卖数量、订单去重、风险限额、人工确认和逐笔操作日志。")

elif page == "系统设置":
    st.subheader("DeepSeek 官方 API")
    cfg = api_config()
    if is_cloud():
        st.caption("站主在 Streamlit 控制台 App settings → Secrets 配置密钥；禁止把 Secrets 文件提交 GitHub。")
    else:
        st.code("编辑项目根目录 .env\nDEEPSEEK_API_KEY=你自己的密钥\nDEEPSEEK_MODEL=deepseek-flash", language="text")
    st.write(f"模型：{cfg['model']} · Key：{'已填写（隐藏）' if cfg['key'] else '未填写'}")
    st.caption("修改 .env 保存后立即读取。页面不显示和保存密钥，禁止把密钥放入聊天或代码。")
    if st.button("测试官方连接 / 获取模型列表", disabled=not owner_mode):
        try:
            available = DeepSeekClient(store).models()
            if cfg["model"] in available:
                st.success("鉴权和模型列表验证通过；生成调用仍需余额及实际请求验证")
            else:
                st.warning("已连接，但当前模型不在可用列表，请修改 DEEPSEEK_MODEL")
            st.write(available)
        except AIError as exc:
            st.error(str(exc))
    st.subheader("回测交易成本")
    with st.form("fees"):
        commission = st.number_input("佣金率（万分之1.5 = 0.00015）", 0.0, .003, fee_cfg.commission, format="%.5f")
        minimum = st.number_input("每笔最低佣金（元）", 0.0, 100.0, fee_cfg.minimum)
        slippage = st.number_input("单边滑点（基点，5 = 0.05%）", 0.0, 100.0, fee_cfg.slippage_bps)
        sz_transfer = st.checkbox("深圳过户费另向客户收取（请按本人交割单核实）", fee_cfg.shenzhen_transfer_pass_through)
        if st.form_submit_button("保存成本配置并记录修改"):
            store.save_setting("fees", asdict(FeeConfig(commission, minimum, slippage, sz_transfer)))
            st.success("已保存；已有实验仍保留当时费率")
    st.caption("默认佣金万1.5、最低5元；印花税按交易日期切换。沪市过户费计入，深市按中信公开费表默认由券商承担；请以本人交割单核实。经手费等按包含在佣金内处理，未另重复计收。")
    st.subheader("执行状态")
    st.write("紧急停止：开启；模拟执行：禁用；实盘：无实现。第一阶段不提供可绕过执行禁用的开关。")
    st.subheader("API Token 与成本记录")
    st.dataframe(store.rows("api_usage"), width="stretch")
    st.caption("Token来自服务端；未设置单价时费用显示未知。配置单价后只作估算，缓存和峰谷价格以官方账单为准。超时可能已经计费。")
    with st.expander("操作审计（本地 SQLite）"):
        st.dataframe(store.rows("audit"), width="stretch")
