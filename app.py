from __future__ import annotations

from dataclasses import dataclass, replace
from io import BytesIO
import json
import re

import pandas as pd
import streamlit as st

try:
    import pdfplumber
except Exception:
    pdfplumber = None

try:
    from google import genai
    from google.genai import types
except Exception:
    genai = None
    types = None

st.set_page_config(page_title="不動産投資シミュレーター", page_icon="🏠", layout="wide")


@dataclass
class Inputs:
    purchase_price: float
    sale_price: float
    rent_monthly: float
    vacancy_rate: float
    interest_rate: float
    loan_years: int
    holding_years: int
    down_payment: float
    purchase_cost_rate: float
    sale_cost_rate: float
    management_monthly: float
    repair_monthly: float
    property_city_tax_yearly: float
    assessment_ratio: float
    management_outsource_rate: float
    restoration_equipment_yearly: float
    building_ratio: float
    useful_life_years: int
    income_tax_rate: float
    capital_gain_tax_rate: float


def yen(v: float) -> str:
    return f"{v:,.0f} 万円"


def yen1(v: float) -> str:
    return f"{v:,.1f} 万円"


def monthly_payment(principal: float, rate: float, years: int) -> float:
    n = years * 12
    mrate = rate / 100 / 12
    if n <= 0:
        return 0.0
    if mrate == 0:
        return principal / n
    return principal * mrate * (1 + mrate) ** n / ((1 + mrate) ** n - 1)


def property_city_tax(price: float, assessment_ratio: float) -> float:
    return price * assessment_ratio / 100 * 1.7 / 100


def simulate(i: Inputs) -> dict:
    loan = max(i.purchase_price - i.down_payment, 0)
    pay_m = monthly_payment(loan, i.interest_rate, i.loan_years)
    building = i.purchase_price * i.building_ratio / 100
    land = i.purchase_price - building
    dep_y = building / i.useful_life_years
    balance = loan
    rows = []
    cf_sum = tax_sum = dep_sum = vacancy_sum = outsource_sum = 0.0
    for y in range(1, i.holding_years + 1):
        interest = principal = 0.0
        for _ in range(12):
            intr = balance * i.interest_rate / 100 / 12
            prin = max(min(pay_m - intr, balance), 0)
            balance = max(balance - prin, 0)
            interest += intr
            principal += prin
        gross = i.rent_monthly * 12
        vacancy = gross * i.vacancy_rate / 100
        rent = gross - vacancy
        mgmt = i.management_monthly * 12
        repair = i.repair_monthly * 12
        outsource = rent * i.management_outsource_rate / 100
        expenses = mgmt + repair + i.property_city_tax_yearly + outsource + i.restoration_equipment_yearly
        loan_payment = interest + principal
        cf = rent - expenses - loan_payment
        taxable = rent - expenses - interest - dep_y
        tax_effect = -taxable * i.income_tax_rate / 100
        cf_sum += cf
        tax_sum += tax_effect
        dep_sum += dep_y
        vacancy_sum += vacancy
        outsource_sum += outsource
        rows.append({"年": y, "満室想定家賃": gross, "空室損失": vacancy, "実効家賃収入": rent, "建物管理費": mgmt, "修繕積立金": repair, "固定資産税・都市計画税": i.property_city_tax_yearly, "管理委託料": outsource, "原状回復・設備交換費": i.restoration_equipment_yearly, "ローン返済": loan_payment, "うち利息": interest, "うち元本": principal, "減価償却": dep_y, "税務上所得": taxable, "税効果": tax_effect, "税前CF": cf, "税後CF": cf + tax_effect, "ローン残債": balance})
    sale_cost = i.sale_price * i.sale_cost_rate / 100
    building_book = max(building - dep_sum, 0)
    acquisition = land + building_book
    gain = i.sale_price - acquisition - sale_cost
    gain_tax = max(gain, 0) * i.capital_gain_tax_rate / 100
    sale_cash = i.sale_price - sale_cost - balance - gain_tax
    purchase_cost = i.purchase_price * i.purchase_cost_rate / 100
    initial_cash = i.down_payment + purchase_cost
    final_profit = cf_sum + tax_sum + sale_cash - initial_cash
    return {"rows": pd.DataFrame(rows), "loan_amount": loan, "monthly_payment": pay_m, "building_price": building, "land_price": land, "yearly_depreciation": dep_y, "cumulative_depreciation": dep_sum, "loan_balance": balance, "sale_cost": sale_cost, "purchase_cost": purchase_cost, "building_book_value": building_book, "acquisition_cost": acquisition, "capital_gain": gain, "capital_gain_tax": gain_tax, "sale_cash_after_tax": sale_cash, "cumulative_cf": cf_sum, "cumulative_tax_effect": tax_sum, "initial_cash_out": initial_cash, "final_profit": final_profit, "total_vacancy_loss": vacancy_sum, "total_outsource_fee": outsource_sum}


def analyze_years(i: Inputs, max_years: int) -> pd.DataFrame:
    rows = []
    for y in range(1, max_years + 1):
        r = simulate(replace(i, holding_years=y))
        rows.append({"保有年数": y, "最終利益": r["final_profit"], "運用中CF": r["cumulative_cf"], "税効果": r["cumulative_tax_effect"], "売却時手残り": r["sale_cash_after_tax"], "ローン残債": r["loan_balance"]})
    return pd.DataFrame(rows)


def render_result_layout(i: Inputs, r: dict) -> None:
    df = r["rows"]
    years = i.holding_years
    yearly_gross = i.rent_monthly * 12
    yearly_vacancy = yearly_gross * i.vacancy_rate / 100
    yearly_effective = yearly_gross - yearly_vacancy
    yearly_management = i.management_monthly * 12
    yearly_repair = i.repair_monthly * 12
    yearly_outsource = yearly_effective * i.management_outsource_rate / 100
    yearly_expenses = yearly_management + yearly_repair + i.property_city_tax_yearly + yearly_outsource + i.restoration_equipment_yearly
    avg_cf = r["cumulative_cf"] / years if years else 0
    avg_taxable = df["税務上所得"].mean() if not df.empty else 0
    avg_interest = df["うち利息"].mean() if not df.empty else 0
    avg_loan_payment = df["ローン返済"].mean() if not df.empty else 0
    st.subheader("結論")
    cols = st.columns(5)
    cols[0].metric("最終利益", yen(r["final_profit"]))
    cols[1].metric("運用中CF", yen(r["cumulative_cf"]))
    cols[2].metric("運用中の税効果", yen(r["cumulative_tax_effect"]))
    cols[3].metric("売却時手残り", yen(r["sale_cash_after_tax"]))
    cols[4].metric("初期持ち出し", yen(r["initial_cash_out"]))
    st.info("最終利益 ＝ 運用中CF ＋ 運用中の税効果 ＋ 売却時手残り － 初期持ち出し")
    st.subheader("計算内訳")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("### ① ローン")
        st.write(f"借入額 = {yen(r['loan_amount'])}")
        st.write(f"毎月返済 = {yen1(r['monthly_payment'])}")
        st.write(f"{years}年後の残債 = {yen(r['loan_balance'])}")
        st.write(f"平均年間ローン返済 = {yen(avg_loan_payment)}")
    with c2:
        st.markdown("### ② 減価償却")
        st.write(f"建物価格 = {yen(r['building_price'])}")
        st.write(f"土地価格 = {yen(r['land_price'])}")
        st.write(f"年間減価償却 = {yen(r['yearly_depreciation'])}")
        st.write(f"減価償却累計 = {yen(r['cumulative_depreciation'])}")
    with c3:
        st.markdown("### ③ 譲渡所得")
        st.write(f"建物簿価 = {yen(r['building_book_value'])}")
        st.write(f"取得費 = 土地簿価 + 建物簿価 = {yen(r['acquisition_cost'])}")
        st.write(f"譲渡所得 = 売却価格 - 取得費 - 売却費用 = {yen(r['capital_gain'])}")
        st.write(f"譲渡所得税 = {yen(r['capital_gain_tax'])}")
    st.subheader("数式")
    st.code(f"""
最終利益
= 運用中CF + 運用中の税効果 + 売却時手残り - 初期持ち出し
= {r['cumulative_cf']:.0f} + {r['cumulative_tax_effect']:.0f} + {r['sale_cash_after_tax']:.0f} - {r['initial_cash_out']:.0f}
= {r['final_profit']:.0f} 万円

運用中CF
= 平均年間CF × 保有年数
= {avg_cf:.0f} × {years}
= {r['cumulative_cf']:.0f} 万円

平均年間CF
= 実効家賃収入 - 年間経費 - 平均年間ローン返済
= {yearly_effective:.0f} - {yearly_expenses:.0f} - {avg_loan_payment:.0f}
= {avg_cf:.0f} 万円

実効家賃収入
= 月額家賃 × 12か月 - 空室損失
= {i.rent_monthly:.1f} × 12 - {yearly_vacancy:.0f}
= {yearly_effective:.0f} 万円

年間経費
= 建物管理費 + 修繕積立金 + 固定資産税・都市計画税 + 管理委託料 + 原状回復・設備交換費
= {yearly_management:.0f} + {yearly_repair:.0f} + {i.property_city_tax_yearly:.0f} + {yearly_outsource:.0f} + {i.restoration_equipment_yearly:.0f}
= {yearly_expenses:.0f} 万円

運用中の税効果
= - 平均税務上所得 × 運用中税率 × 保有年数
= - ({avg_taxable:.0f}) × {i.income_tax_rate:.1f}% × {years}
= {r['cumulative_tax_effect']:.0f} 万円

平均税務上所得
= 実効家賃収入 - 年間経費 - 平均支払利息 - 減価償却
= {yearly_effective:.0f} - {yearly_expenses:.0f} - {avg_interest:.0f} - {r['yearly_depreciation']:.0f}
= {avg_taxable:.0f} 万円

売却時手残り
= 売却価格 - 売却費用 - ローン残債 - 譲渡所得税
= {i.sale_price:.0f} - {r['sale_cost']:.0f} - {r['loan_balance']:.0f} - {r['capital_gain_tax']:.0f}
= {r['sale_cash_after_tax']:.0f} 万円

譲渡所得
= 売却価格 - 取得費 - 売却費用
= {i.sale_price:.0f} - {r['acquisition_cost']:.0f} - {r['sale_cost']:.0f}
= {r['capital_gain']:.0f} 万円
""", language="text")


def extract_pdf_text(uploaded_file) -> str:
    if pdfplumber is None:
        st.error("pdfplumber がありません。再デプロイしてください。")
        return ""
    pages = []
    with pdfplumber.open(BytesIO(uploaded_file.getvalue())) as pdf:
        for idx, p in enumerate(pdf.pages, start=1):
            pages.append(f"--- PAGE {idx} ---\n{p.extract_text(x_tolerance=2, y_tolerance=3) or ''}")
    return "\n\n".join(pages)


def as_float(v) -> float | None:
    if v in [None, "", "null"]:
        return None
    try:
        return float(str(v).replace(",", ""))
    except Exception:
        return None


def parse_rule(uploaded_file) -> pd.DataFrame:
    text = extract_pdf_text(uploaded_file)
    rows = []
    for page in text.split("--- PAGE "):
        lines = [x.strip() for x in page.splitlines() if x.strip()]
        if len(lines) < 2:
            continue
        header = lines[1] if lines[0].isdigit() else lines[0]
        m = re.match(r"(.+?)\s+([0-9,]+)$", header)
        if not m:
            continue
        money = [int(x.group(1).replace(",", "")) for x in re.finditer(r"(?:￥|¥)?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,})\s*円", page)]
        price = float(m.group(2).replace(",", ""))
        annual = money[0] / 10000 if len(money) > 0 else None
        monthly = money[1] / 10000 if len(money) > 1 else None
        repair = money[2] / 10000 if len(money) > 2 else None
        management = money[3] / 10000 if len(money) > 3 else None
        rows.append({"物件名": m.group(1).strip(), "価格": price, "月額家賃": monthly, "年間家賃": annual, "修繕積立金/月": repair, "建物管理費/月": management, "賃貸状態": next((s for s in ["賃貸中", "サブリース中", "空室"] if s in page), ""), "表面利回り%": annual / price * 100 if annual and price else None, "抽出方法": "ルール", "抽出メモ": "要確認"})
    return pd.DataFrame(rows)


def gemini_models() -> list[str]:
    preferred = st.secrets.get("GEMINI_MODEL", "gemini-2.5-flash")
    out = []
    for m in [preferred, "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
        if m and m not in out:
            out.append(m)
    return out


def parse_ai(uploaded_file) -> pd.DataFrame:
    if genai is None or types is None:
        st.error("google-genai がありません。再デプロイしてください。")
        return pd.DataFrame()
    api_key = st.secrets.get("GEMINI" + "_API" + "_KEY", None)
    if not api_key:
        st.error("Streamlit Secrets に Gemini APIキーが見つかりません。")
        return pd.DataFrame()
    text = extract_pdf_text(uploaded_file)
    if not text.strip():
        st.warning("PDFからテキストを抽出できませんでした。")
        return pd.DataFrame()
    prompt = f"""日本の不動産投資資料から物件情報を抽出してください。単位は万円に統一。円表記は10000で割る。価格が「6,270」なら「6,270万円」。管理費と修繕積立金は取り違えない。不明なら null。返答はJSONのみ。
{{"properties":[{{"物件名":"","所在地":"","価格":0,"月額家賃":0,"年間家賃":0,"建物管理費/月":0,"修繕積立金/月":0,"賃貸状態":"","築年月":"","構造":"","専有面積㎡":0,"駅徒歩":"","抽出メモ":""}}]}}
PDF抽出テキスト：
{text[:50000]}"""
    client = genai.Client(api_key=api_key)
    data = None
    used_model = None
    last_error = None
    for model in gemini_models():
        try:
            resp = client.models.generate_content(model=model, contents=prompt, config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0))
            data = json.loads(resp.text or "{}")
            used_model = model
            break
        except Exception as exc:
            last_error = exc
    if data is None:
        st.error("Gemini AI抽出でエラーが発生しました。")
        if last_error:
            st.exception(last_error)
        return pd.DataFrame()
    st.caption(f"Gemini使用モデル: {used_model}")
    rows = []
    for p in data.get("properties", []):
        price = as_float(p.get("価格"))
        monthly = as_float(p.get("月額家賃"))
        annual = as_float(p.get("年間家賃")) or (monthly * 12 if monthly else None)
        rows.append({"物件名": p.get("物件名"), "所在地": p.get("所在地"), "価格": price, "月額家賃": monthly, "年間家賃": annual, "修繕積立金/月": as_float(p.get("修繕積立金/月")), "建物管理費/月": as_float(p.get("建物管理費/月")), "賃貸状態": p.get("賃貸状態"), "築年月": p.get("築年月"), "構造": p.get("構造"), "専有面積㎡": as_float(p.get("専有面積㎡")), "駅徒歩": p.get("駅徒歩"), "表面利回り%": annual / price * 100 if annual and price else None, "抽出方法": f"Gemini AI({used_model})", "抽出メモ": p.get("抽出メモ", "OK")})
    return pd.DataFrame(rows)


def inputs_from_row(row: pd.Series, d: dict) -> Inputs:
    price = float(row["価格"])
    return Inputs(price, price * d["sale_price_rate"] / 100, float(row["月額家賃"] or 0), d["vacancy_rate"], d["interest_rate"], d["loan_years"], d["holding_years"], price * d["down_payment_rate"] / 100, d["purchase_cost_rate"], d["sale_cost_rate"], float(row.get("建物管理費/月") or 0), float(row.get("修繕積立金/月") or 0), property_city_tax(price, d["assessment_ratio"]), d["assessment_ratio"], d["management_outsource_rate"], d["restoration_equipment_yearly"], d["building_ratio"], d["useful_life_years"], d["income_tax_rate"], d["capital_gain_tax_rate"])


def format_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    text_cols = {"物件名", "所在地", "賃貸状態", "築年月", "構造", "駅徒歩", "抽出方法", "抽出メモ", "年", "保有年数"}
    for c in out.columns:
        if c not in text_cols:
            out[c] = out[c].map(lambda x: "" if pd.isna(x) else f"{x:,.1f}")
    return out


def render_single() -> None:
    with st.expander("入力項目", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        purchase = c1.number_input("購入価格（万円）", 500.0, 30000.0, 3000.0, 100.0)
        sale = c1.number_input("売却価格（万円）", 500.0, 30000.0, 3000.0, 100.0)
        rent = c1.number_input("月額家賃（万円）", 1.0, 300.0, 10.0, 1.0)
        vacancy = c1.number_input("空室率（%）", 0.0, 30.0, 5.0, 0.5)
        down = c2.number_input("頭金（万円）", 0.0, 30000.0, 0.0, 100.0)
        rate = c2.number_input("金利（%）", 0.0, 10.0, 2.0, 0.1)
        loan_years = c2.number_input("ローン年数", 1, 50, 35, 1)
        hold = c2.number_input("保有年数", 1, 50, 5, 1)
        max_y = c2.number_input("最適保有年数分析の上限", 1, 50, min(35, int(loan_years)), 1)
        mgmt = c3.number_input("月額建物管理費（万円）", 0.0, 100.0, 1.0, 0.5)
        repair = c3.number_input("月額修繕積立金（万円）", 0.0, 100.0, 1.0, 0.5)
        assess = c3.number_input("評価額割合（%）", 10.0, 100.0, 40.0, 5.0)
        outsource = c3.number_input("管理委託料率（%）", 0.0, 20.0, 5.0, 0.5)
        restoration = c4.number_input("原状回復・設備交換費/年（万円）", 0.0, 500.0, 10.0, 1.0)
        purchase_cost = c4.number_input("購入諸費用率（%）", 0.0, 20.0, 7.0, 0.5)
        sale_cost = c4.number_input("売却諸費用率（%）", 0.0, 20.0, 4.0, 0.5)
        building_ratio = c4.number_input("建物割合（%）", 0.0, 100.0, 80.0, 5.0)
        life = c4.number_input("償却年数", 1, 60, 47, 1)
        income_tax = c4.number_input("運用中税率（%）", 0.0, 60.0, 20.0, 1.0)
        gain_tax = c4.number_input("譲渡所得税率（%）", 0.0, 60.0, 20.0, 1.0)
    i = Inputs(purchase, sale, rent, vacancy, rate, int(loan_years), int(hold), down, purchase_cost, sale_cost, mgmt, repair, property_city_tax(purchase, assess), assess, outsource, restoration, building_ratio, int(life), income_tax, gain_tax)
    r = simulate(i)
    render_result_layout(i, r)
    st.subheader("年次キャッシュフロー")
    st.dataframe(format_df(r["rows"]), use_container_width=True, hide_index=True)
    st.line_chart(r["rows"].set_index("年")[["実効家賃収入", "税前CF", "税後CF", "ローン残債"]])
    st.subheader("最適保有年数分析")
    a = analyze_years(i, int(max_y))
    best = a.loc[a["最終利益"].idxmax()]
    b1, b2, b3 = st.columns(3)
    b1.metric("最適保有年数", f"{int(best['保有年数'])} 年")
    b2.metric("最大最終利益", yen(best["最終利益"]))
    b3.metric("売却時手残り", yen(best["売却時手残り"]))
    st.line_chart(a.set_index("保有年数")[["最終利益", "運用中CF", "売却時手残り", "ローン残債"]])


def render_pdf() -> None:
    st.subheader("PDF自動読み取り・複数物件比較")
    mode = st.radio("抽出方式", ["Gemini AI抽出", "ルール抽出"], horizontal=True)
    uploaded = st.file_uploader("物件PDFをアップロード", type=["pdf"])
    with st.expander("共通前提", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        d = {"vacancy_rate": c1.number_input("空室率%", 0.0, 30.0, 10.0, 0.5, key="v"), "interest_rate": c1.number_input("金利%", 0.0, 10.0, 2.0, 0.1, key="r"), "loan_years": int(c1.number_input("ローン年数", 1, 50, 35, 1, key="ly")), "holding_years": int(c2.number_input("保有年数", 1, 50, 5, 1, key="hy")), "sale_price_rate": c2.number_input("売却価格/購入価格%", 50.0, 150.0, 100.0, 1.0, key="sp"), "down_payment_rate": c2.number_input("頭金率%", 0.0, 100.0, 0.0, 5.0, key="dp"), "purchase_cost_rate": c3.number_input("購入諸費用率%", 0.0, 20.0, 7.0, 0.5, key="pc"), "sale_cost_rate": c3.number_input("売却諸費用率%", 0.0, 20.0, 4.0, 0.5, key="sc"), "assessment_ratio": c3.number_input("評価額割合%", 10.0, 100.0, 40.0, 5.0, key="ar"), "management_outsource_rate": c4.number_input("管理委託料率%", 0.0, 20.0, 5.0, 0.5, key="mo"), "restoration_equipment_yearly": c4.number_input("原状回復・設備交換費/年", 0.0, 500.0, 10.0, 1.0, key="re"), "building_ratio": c4.number_input("建物割合%", 0.0, 100.0, 80.0, 5.0, key="br"), "useful_life_years": 47, "income_tax_rate": 20.0, "capital_gain_tax_rate": 20.0}
    if not uploaded:
        st.info("PDFをアップロードすると抽出結果とランキングを表示します。")
        return
    with st.spinner("PDFを読み取り中..."):
        extracted = parse_ai(uploaded) if mode == "Gemini AI抽出" else parse_rule(uploaded)
    if extracted.empty:
        st.warning("物件情報を抽出できませんでした。")
        return
    edited = st.data_editor(extracted, use_container_width=True, hide_index=True, num_rows="dynamic")
    results, details = [], {}
    for _, row in edited.dropna(subset=["価格", "月額家賃"]).iterrows():
        i = inputs_from_row(row, d)
        r = simulate(i)
        details[row["物件名"]] = (i, r)
        results.append({"物件名": row["物件名"], "価格": i.purchase_price, "月額家賃": i.rent_monthly, "修繕積立金/月": i.repair_monthly, "建物管理費/月": i.management_monthly, "表面利回り%": row.get("表面利回り%"), "最終利益": r["final_profit"], "運用中CF": r["cumulative_cf"], "税効果": r["cumulative_tax_effect"], "売却時手残り": r["sale_cash_after_tax"], "空室損失累計": r["total_vacancy_loss"], "ローン残債": r["loan_balance"], "賃貸状態": row.get("賃貸状態", "")})
    result_df = pd.DataFrame(results).sort_values("最終利益", ascending=False)
    st.subheader("比較ランキング")
    st.dataframe(format_df(result_df), use_container_width=True, hide_index=True)
    st.bar_chart(result_df.set_index("物件名")[["最終利益", "運用中CF", "売却時手残り"]])
    selected = st.selectbox("詳細を見る物件", result_df["物件名"].tolist())
    if selected:
        i, r = details[selected]
        render_result_layout(i, r)
        st.dataframe(format_df(r["rows"]), use_container_width=True, hide_index=True)
    st.download_button("比較結果CSVをダウンロード", result_df.to_csv(index=False).encode("utf-8-sig"), "real_estate_comparison.csv", "text/csv")


def main() -> None:
    st.title("🏠 不動産投資・税金対策シミュレーター")
    st.caption("減価償却、運用中CF、譲渡所得、売却時手残り、最終利益を一画面で確認します。単位は万円です。")
    t1, t2 = st.tabs(["単独物件分析", "PDF複数物件比較"])
    with t1:
        render_single()
    with t2:
        render_pdf()
    st.caption("注意：本アプリは概算シミュレーションです。実際の税務判断は税理士等に確認してください。")


if __name__ == "__main__":
    main()
